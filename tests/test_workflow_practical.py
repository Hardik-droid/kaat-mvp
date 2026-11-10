"""Practical safety/state regressions; media and MCP checks execute real tools."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import subprocess
import sys

import pytest

from commands import parse_command
from controller import AgentController
from engine import _binary, duration, source_hash
from memory import Memory


@pytest.mark.parametrize('text', [
    'Kaat, I love to remove pauses',
    'Kaat, I always remove pauses',
    'Kaat, the word export appears in this example',
    'Kaat, it is fun to remove pauses',
    'Kaat, no export',
    'Kaat, not remove pauses',
    'Kaat, kya export hota hai',
    'Kaat, approve all cuts and export',
    'Kaat, undo and clear edits',
    'Kaat, remove pauses and export',
    'Kaat, remove pauses shorter than 2 seconds',
    'Kaat, remove pauses over half a second',
    'Kaat, remove pauses over 2 or 3 seconds',
    'Kaat, remove pauses over 2 seconds or 3 seconds',
    'Kaat, remove pauses over 1e-3 seconds',
    'Kaat, remove pauses over 2,5 seconds',
    'Kaat, remove pauses over 2 to 3 seconds',
])
def test_narration_ambiguous_compounds_and_unsupported_thresholds_take_no_action(text):
    assert parse_command(text)[0] == 'unknown'


@pytest.mark.parametrize('text, seconds', [
    ('Kaat, remove pauses over -2 seconds', -2.0),
    ('Kaat, remove pauses over .5 seconds', .5),
    ('Kaat, remove pauses over 500 milliseconds', .5),
    ('Kaat, remove pauses over 2 minutes', 120.0),
    ('Kaat, remove pauses over two point five seconds', 2.5),
])
def test_duration_sign_decimal_and_units_are_not_silently_changed(text, seconds):
    assert parse_command(text) == ('analyse', {'seconds': seconds})


def test_subtitle_negation_is_an_explicit_false_option():
    assert parse_command('Kaat, export without subtitles') == ('export', {'subtitles': False})
    assert parse_command('Kaat, export with no subtitles') == ('export', {'subtitles': False})


def test_hinglish_delete_preference_is_not_pause_analysis():
    assert parse_command('Kaat, pause settings hata de') == ('delete_preference', {'key': 'pause_threshold'})


@pytest.fixture(scope='module')
def media(tmp_path_factory):
    folder = tmp_path_factory.mktemp('practical_workflow')
    source = folder / 'recording.mp4'
    subprocess.run([_binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
                    '-f', 'lavfi', '-i', 'testsrc2=size=160x120:rate=25:duration=5',
                    '-f', 'lavfi', '-i', r'aevalsrc=if(between(t\,1\,4)\,0\,0.15*sin(2*PI*440*t)):s=48000:d=5',
                    '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(source)],
                   check=True, capture_output=True, timeout=30)
    return source


@pytest.fixture
def agent(media, tmp_path):
    result = AgentController(tmp_path / 'kaat.sqlite3')
    assert result.call('video.inspect', source=str(media))['ok']
    return result


def test_repeated_pause_detection_returns_real_stable_ids_and_preserves_restore(agent):
    first = agent.call('video.detect_pauses')['data']['cuts']
    assert len(first) == 1
    cut_id = first[0]['id']
    assert agent.call('video.approve_cut', cut_id=cut_id)['ok']
    second = agent.call('video.detect_pauses')['data']['cuts']
    assert second[0]['id'] == cut_id and second[0]['status'] == 'approved'
    assert agent.call('video.approve_cut', cut_id=second[0]['id'])['ok']
    assert agent.call('video.undo')['ok']
    assert agent.state()['cuts'][0]['status'] == 'suggested'
    assert agent.call('video.restore_cut', cut_id=cut_id)['ok']
    third = agent.call('video.detect_pauses')['data']['cuts']
    assert third[0]['id'] == cut_id and third[0]['status'] == 'restored'
    assert agent.state()['edited_duration'] == 5.0


def test_repeated_retake_detection_returns_ids_that_can_be_approved(agent):
    assert agent.call('video.import_transcript', segments=[
        {'start': 0, 'end': 2, 'text': 'Today we are explaining how artificial intelligence can help us', 'timing': 'segment'},
        {'start': 3, 'end': 5, 'text': 'Today we are explaining how artificial intelligence can help us', 'timing': 'segment'},
    ])['ok']
    first = agent.call('video.detect_retakes')['data']['cuts']
    second = agent.call('video.detect_retakes')['data']['cuts']
    assert len(first) == 1 and first[0]['id'] == second[0]['id']
    assert agent.call('video.approve_cut', cut_id=second[0]['id'])['ok']
    assert len(agent.state()['cuts']) == 1


def test_compound_hinglish_pause_last_take_and_captions_executes_real_tools(agent, tmp_path):
    assert agent.call('video.import_transcript', segments=[
        {'start': 0, 'end': .8, 'text': 'Today we explain how artificial intelligence helps creators', 'timing': 'segment'},
        {'start': 4.2, 'end': 5, 'text': 'Today we explain how artificial intelligence helps creators', 'timing': 'segment'},
    ])['ok']
    result = agent.command('Ab unnecessary pauses hata de, last wali take rakhna, aur subtitles add kar dena.')
    assert result['ok'], result
    assert [op['tool'] for op in result['operations']] == ['video.detect_pauses', 'video.detect_retakes']
    state = agent.state()
    assert state['subtitles'] and len(state['cuts']) == 2
    assert all(c['status'] == 'suggested' for c in state['cuts'])
    assert state['edited_duration'] == 5
    assert agent.call('video.approve_all')['ok']
    output = tmp_path / 'compound_result.mp4'
    assert agent.call('video.export', output=str(output))['ok']
    assert output.exists() and output.with_suffix('.srt').exists()
    assert abs(duration(output) - agent.state()['edited_duration']) < .12


def test_noop_approvals_do_not_hide_the_actual_undo(agent):
    cut = agent.call('video.propose_cut', start=1, end=2)['data']
    assert agent.call('video.approve_all')['ok']
    assert agent.call('video.approve_all')['ok']
    assert agent.call('video.approve_cut', cut_id=cut['id'])['ok']
    assert agent.call('video.undo')['ok']
    assert agent.state()['cuts'][0]['status'] == 'suggested'


def test_restoring_one_overlapping_operation_reports_remaining_approved_cut(agent):
    first = agent.call('video.propose_cut', start=1, end=3)['data']
    second = agent.call('video.propose_cut', start=2, end=4)['data']
    assert agent.call('video.approve_all')['ok']
    result = agent.call('video.restore_cut', cut_id=first['id'])
    assert result['ok'] and 'Other approved cuts overlap' in result['data']['warning']
    assert agent.state()['edited_duration'] == 3.0
    assert next(c for c in agent.state()['cuts'] if c['id'] == second['id'])['status'] == 'approved'


@pytest.mark.parametrize('bad_tool', [None, [], {}, 42, ''])
def test_invalid_tool_names_always_return_structured_errors(tmp_path, bad_tool):
    agent = AgentController(tmp_path / 'memory.sqlite3')
    result = agent.call(bad_tool)
    assert result['ok'] is False and isinstance(result['error']['message'], str)


def test_unknown_tools_report_unknown_even_before_media_selection(tmp_path):
    agent = AgentController(tmp_path / 'memory.sqlite3')
    result = agent.call('video.execute_arbitrary_shell')
    assert result['ok'] is False and 'Unknown tool' in result['error']['message']


@pytest.mark.parametrize('start,end', [(True, 2), (0, False)])
def test_boolean_cut_boundaries_do_not_become_seconds(agent, start, end):
    assert not agent.call('video.propose_cut', start=start, end=end)['ok']
    assert agent.state()['cuts'] == []


def test_wrong_subtitle_type_cannot_render_or_create_outputs(agent, tmp_path):
    output = tmp_path / 'wrong_bool.mp4'
    response = agent.call('video.export', output=str(output), subtitles='false')
    assert not response['ok'] and 'true or false' in response['error']['message']
    assert not output.exists()


def test_command_explicitly_disables_previously_requested_subtitles(agent, tmp_path):
    agent.subtitle_requested = True
    output = tmp_path / 'without_captions.mp4'
    response = agent.command('Kaat, export without subtitles', output=str(output))
    assert response['ok'], response
    assert agent.state()['subtitles'] is False
    assert output.exists() and not output.with_suffix('.srt').exists()
    assert abs(duration(output) - 5) < .12


def test_invalid_duration_commands_do_not_fall_back_to_two_seconds(agent):
    for request in ('Kaat, remove pauses over -2 seconds', 'Kaat, remove pauses over 2 minutes'):
        result = agent.command(request)
        assert result['ok'] is False
        assert agent.state()['cuts'] == [] and agent.state()['pause_threshold'] == 2.0


def test_external_source_replacement_requires_reselection(media, tmp_path):
    source = tmp_path / 'changing.mp4'
    source.write_bytes(media.read_bytes())
    agent = AgentController(tmp_path / 'memory.sqlite3')
    assert agent.call('video.inspect', source=str(source))['ok']
    with source.open('ab') as handle:
        handle.write(b'external writer changed source')
    result = agent.call('video.detect_pauses')
    assert not result['ok'] and 'source changed' in result['error']['message']
    assert agent.call('video.inspect', source=str(source))['ok']
    assert agent.call('video.detect_pauses')['ok']


def test_unavailable_history_does_not_disguise_completed_media_action(media, tmp_path):
    dbpath = tmp_path / 'memory.sqlite3'
    agent = AgentController(dbpath)
    dbpath.rename(tmp_path / 'memory_backup.sqlite3')
    dbpath.mkdir()
    result = agent.call('video.inspect', source=str(media))
    assert result['ok'] and result['warnings']
    state = agent.state()
    assert state['source'] == str(media) and state['memory_warning']
    failure = agent.call('unknown')
    assert not failure['ok'] and 'Unknown tool' in failure['error']['message']


def test_independent_sqlite_connections_preserve_concurrent_preferences_and_history(tmp_path):
    path = tmp_path / 'memory.sqlite3'
    Memory(path)
    def write(index):
        memory = Memory(path)
        memory.save('pause_threshold' if index % 2 else 'burn_subtitles', 3.0 if index % 2 else True, approved=True)
        memory.record('parallel.test', True, f'operation {index}')
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(write, range(20)))
    memory = Memory(path)
    assert memory.preferences() == {'pause_threshold': 3.0, 'burn_subtitles': True}
    assert len(memory.history()) == 20
    with pytest.raises(ValueError):
        memory.delete('unknown_key')


def test_task_history_retains_only_latest_500_results(tmp_path):
    memory = Memory(tmp_path / 'bounded.sqlite3')
    for index in range(505):
        memory.record('real.history.write', True, str(index))
    rows = memory.history(500)
    assert len(rows) == 500
    assert rows[0]['detail'] == '504' and rows[-1]['detail'] == '5'


def test_mcp_repeated_detection_approval_undo_and_real_subtitle_export(media, tmp_path):
    before = source_hash(media)
    output = tmp_path / 'protocol_captions.mp4'
    async def run():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
        import os
        root = Path(__file__).resolve().parents[1]
        params = StdioServerParameters(command=sys.executable, args=[str(root/'mcp_server.py')], cwd=str(root),
                                       env=dict(os.environ, KAAT_DATA_DIR=str(tmp_path/'protocol_memory')))
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                async def call(tool, **args):
                    result = await session.call_tool(tool, args)
                    assert not result.isError, result
                    data = result.structuredContent or json.loads(result.content[0].text)
                    assert data['ok'], data
                    return data['data']
                await call('video.inspect', source=str(media))
                cuts = (await call('video.detect_pauses'))['cuts']
                await call('video.approve_cut', cut_id=cuts[0]['id'])
                repeated = (await call('video.detect_pauses'))['cuts']
                assert repeated[0]['id'] == cuts[0]['id']
                await call('video.approve_cut', cut_id=repeated[0]['id'])
                await call('video.undo')
                assert (await call('session.state'))['cuts'][0]['status'] == 'suggested'
                await call('video.approve_all')
                # These independent verified cues survive in full. The former
                # whole-recording cue could repeat words from deleted content.
                await call('video.import_transcript', segments=[
                    {'start': 0, 'end': .8, 'text': 'First intact supplied cue.', 'timing': 'segment'},
                    {'start': 4.2, 'end': 5, 'text': 'Second intact supplied cue.', 'timing': 'segment'}])
                result = await call('video.export', output=str(output), subtitles=True)
                assert result['subtitles'] == str(output.with_suffix('.srt'))
                assert result['caption_source'] == 'source_timestamps'
    asyncio.run(asyncio.wait_for(run(), 60))
    assert output.exists() and output.with_suffix('.srt').exists() and output.with_suffix('.kaat-edl.json').exists()
    captions = output.with_suffix('.srt').read_text(encoding='utf-8')
    assert 'First intact supplied cue.' in captions and 'Second intact supplied cue.' in captions
    assert source_hash(media) == before and duration(output) < 3
