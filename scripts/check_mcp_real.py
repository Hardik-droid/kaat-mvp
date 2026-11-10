"""Actual MCP -> Prisma -> FFmpeg human-speech workflow, with no provider mocks.

Requires the public-speech fixture prepared for practical testing (or an explicit
source video). Makes actual Prisma calls for every audio chunk. Does not touch
the microphone, mouse, camera or other desktop windows.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import Cut, _binary, duration, inspect_video, render, source_hash


async def workflow(source, output, report):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    params = StdioServerParameters(command=sys.executable, args=[str(ROOT/'mcp_server.py')],
        cwd=str(ROOT), env=dict(os.environ, KAAT_DATA_DIR=str(output/'memory')))
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            report['protocol_initialized'] = True
            report['available_tools'] = [tool.name for tool in (await session.list_tools()).tools]

            async def call(name, expected_ok=True, **args):
                started = time.monotonic()
                result = await session.call_tool(name, args)
                if result.isError:
                    raise RuntimeError(f'MCP protocol tool error for {name}')
                response = result.structuredContent
                if response is None:
                    response = json.loads(result.content[0].text)
                report['steps'].append({'tool': name, 'elapsed_seconds': round(time.monotonic()-started, 3),
                                        'expected_ok': expected_ok, 'response': response})
                if response['ok'] != expected_ok:
                    raise RuntimeError(f'{name}: {response.get("error", "Unexpected success")}')
                return response.get('data') if expected_ok else response.get('error')

            await call('video.inspect', source=str(source))
            suggestions = await call('video.detect_pauses')
            assert suggestions['cuts'], 'Expected the known inserted speech gap to produce a real proposal'
            state = await call('session.state')
            assert state['original_duration'] == state['edited_duration'], 'Suggestions changed the export without approval'
            transcript = await call('video.transcribe')
            report['provider_segments'] = transcript['segments']
            assert any(segment['text'].strip() for segment in transcript['segments']), 'Actual provider returned no speech on known speech'
            assert all(segment['timing'] == 'chunk_only' for segment in transcript['segments'])
            assert not transcript['word_timestamps'], 'Provider text cannot supply invented word alignment'
            retakes = await call('video.detect_retakes')
            report['retake_suggestions'] = retakes['cuts']
            assert all(cut['status'] == 'suggested' for cut in retakes['cuts'])
            cut_id = suggestions['cuts'][0]['id']
            await call('video.approve_cut', cut_id=cut_id)
            state = await call('session.state')
            approved_duration = state['edited_duration']
            assert approved_duration < state['original_duration'] - 2
            await call('video.undo')
            state = await call('session.state')
            assert state['original_duration'] == state['edited_duration']
            await call('video.approve_cut', cut_id=cut_id)
            await call('video.restore_cut', cut_id=cut_id)
            state = await call('session.state')
            assert state['original_duration'] == state['edited_duration']
            await call('video.undo')
            state = await call('session.state')
            assert state['edited_duration'] == approved_duration
            report['approved_operations'] = [cut for cut in state['cuts'] if cut['status'] == 'approved']
            exported = await call('video.export', output=str(output/'human_captioned.mp4'), subtitles=True)
            report['export'] = exported
            expected = await call('camera.start_recording', expected_ok=False)
            report['recording_status'] = {'supported': False, 'reported_error': expected,
                'interpretation': 'Expected unsupported error; recording is not counted as a passing capability'}
            await call('video.export', expected_ok=False, output=str(source), subtitles=False)


def run(source, output):
    source, output = Path(source).resolve(strict=True), Path(output).resolve()
    if duration(source) > 50:
        raise ValueError('This bounded account check accepts at most 50 seconds / two Prisma requests')
    if output.exists() and any(output.iterdir()):
        raise ValueError('Choose an empty output directory; real workflow evidence is never overwritten')
    output.mkdir(parents=True, exist_ok=True)
    before = source_hash(source)
    public_fixture = source == (ROOT/'test_output/practical_speech/human_hinglish_with_pause.mp4').resolve()
    report = {'status': 'running', 'source': str(source), 'source_sha256_before': before,
        'input_description': 'Public human Hindi-English lecture speech on generated test-pattern video with a controlled silence gap' if public_fixture else 'Caller-supplied media; no human speech provenance inferred',
        'source_provenance': 'https://www.openslr.org/104/ (original CC BY-SA 4.0), mirror https://huggingface.co/datasets/dianavdavidson/MUCS-Hinglish' if public_fixture else None,
        'provider_mocks': False, 'microphone_used': False, 'steps': []}
    started = time.monotonic()
    try:
        asyncio.run(asyncio.wait_for(workflow(source, output, report), timeout=180))
        exported = Path(report['export']['output'])
        assert source_hash(source) == before
        actual_duration = duration(exported)
        assert abs(actual_duration-report['export']['edited_duration']) < .12
        srt = Path(report['export']['subtitles'])
        assert srt.is_file() and '-->' in srt.read_text(encoding='utf-8')
        plan = json.loads(Path(report['export']['edl']).read_text(encoding='utf-8'))
        assert plan['source_sha256'] == before
        # Fully decode the actual produced streams, independently from container metadata.
        subprocess.run([_binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
                        '-i', str(exported), '-f', 'null', '-'], check=True, capture_output=True, timeout=60)
        operations = [Cut(**cut) for cut in report['approved_operations']]
        baseline = render(source, operations, output/'human_no_captions.mp4')
        for path, image in ((exported, output/'captioned_frame.png'), (baseline, output/'baseline_frame.png')):
            subprocess.run([_binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
                '-ss', '2', '-i', str(path), '-frames:v', '1', str(image)], check=True, capture_output=True, timeout=30)
        from PIL import Image, ImageChops
        captioned, baseline_frame = [Image.open(output/name).convert('RGB') for name in ('captioned_frame.png','baseline_frame.png')]
        bounds = ImageChops.difference(captioned, baseline_frame).getbbox()
        assert bounds is not None, 'Caption burn produced no visual difference from the same edit without subtitles'
        report.update(status='passed', source_sha256_after=source_hash(source), source_unchanged=True,
            actual_export_seconds=actual_duration, planned_export_seconds=report['export']['edited_duration'],
            decode_succeeded=True, subtitle_frame_difference_bounds=bounds,
            output_streams=[{key: stream.get(key) for key in ('codec_type','codec_name','width','height','duration')}
                            for stream in inspect_video(exported)['streams']],
            remaining_limits=['Chunk captions are coarse and may repeat whole chunk text across retained ranges',
                              'Human assistant-command utterances and physical microphone were not tested by lecture content',
                              'ASR quality is measured separately; this workflow does not claim perfect recognition'])
    except Exception as exc:
        message = str(exc)
        key = os.getenv('GNANI_API_KEY', '')
        report.update(status='failed', error=message.replace(key, '[redacted]') if key else message,
                      source_unchanged=source_hash(source) == before)
    finally:
        report['total_seconds'] = round(time.monotonic()-started, 3)
        (output/'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT/'test_output/practical_speech/human_hinglish_with_pause.mp4')
    parser.add_argument('--output', type=Path, default=ROOT/'test_output/mcp_human')
    args = parser.parse_args()
    result = run(args.source, args.output)
    print(json.dumps({key: value for key, value in result.items() if key not in ('steps','available_tools')}, ensure_ascii=False, indent=2))
    raise SystemExit(result['status'] != 'passed')
