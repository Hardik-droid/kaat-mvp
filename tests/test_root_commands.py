"""Command semantics regressions; FFmpeg is real, no ASR success is simulated."""
import subprocess

import pytest

from commands import parse_command
from controller import AgentController
from engine import _binary, source_hash


@pytest.mark.parametrize('utterance,intent,parameters', [
    ('Kaat, pauses hatao', 'analyse', {}),
    ('Kaat, pauses nikalo', 'analyse', {}),
    ('Kaat, video export kar do', 'export', {}),
    ('Kaat, please can you export the video', 'export', {}),
    ('Kaat, iski pauses remove kar do', 'analyse', {}),
    ('Kaat, add subtitles', 'transcribe', {'subtitles': True}),
    ('Kaat, remove pauses without subtitles', 'analyse', {'subtitles': False}),
    ('Kaat, remove pauses with no subtitles', 'analyse', {'subtitles': False}),
    ('Kaat, transcribe without subtitles', 'transcribe', {'subtitles': False}),
    ('Kaat, subtitles hatao', 'set_subtitles', {'enabled': False}),
    ('Kaat, always add subtitles', 'save_preference', {'key': 'burn_subtitles', 'value': True}),
    ('Kaat, always export without subtitles', 'save_preference', {'key': 'burn_subtitles', 'value': False}),
    ('Kaat, forget subtitle settings', 'delete_preference', {'key': 'burn_subtitles'}),
    ('Kaat, remove pauses and detect retakes', 'analyse', {'detect_retakes': True}),
])
def test_complete_request_semantics(utterance, intent, parameters):
    assert parse_command(utterance) == (intent, parameters)


@pytest.mark.parametrize('utterance', [
    'Kaat, remove the last pause',
    'Kaat, remove the first two pauses',
    'Kaat, remove pauses and keep the first take',
    'Kaat, remove pauses and forget settings',
    'Kaat, forget settings',
    'Kaat, please can you not export the video',
])
def test_unsupported_or_ambiguous_requests_do_not_silently_execute_a_subset(utterance):
    assert parse_command(utterance)[0] == 'unknown'


@pytest.fixture
def source(tmp_path):
    path = tmp_path / 'source.mp4'
    subprocess.run([
        _binary('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'color=c=blue:s=160x120:r=25:d=6',
        '-f', 'lavfi', '-i', r'aevalsrc=if(between(t\,1\,4)\,0\,0.2*sin(2*PI*440*t)):s=16000:d=6',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)
    ], check=True, capture_output=True)
    return path


def test_without_subtitles_never_requests_transcription(source, tmp_path, monkeypatch):
    def unexpected_provider_call(*args, **kwargs):
        pytest.fail('Explicitly disabled captions must not invoke an ASR provider')
    monkeypatch.setattr('engine.prisma_transcribe', unexpected_provider_call)
    agent = AgentController(tmp_path / 'memory.sqlite3')
    assert agent.call('video.inspect', source=str(source))['ok']
    agent.subtitle_requested = True
    fingerprint = source_hash(source)
    result = agent.command('Kaat, remove pauses without subtitles')
    assert result['ok'], result
    assert result['tool'] == 'video.detect_pauses'
    assert agent.state()['subtitles'] is False and agent.state()['transcript'] == []
    assert len(agent.state()['cuts']) == 1
    assert source_hash(source) == fingerprint


def test_subtitle_preference_never_changes_pause_preference(tmp_path):
    path = tmp_path / 'memory.sqlite3'
    agent = AgentController(path)
    assert agent.call('memory.save_preference', key='pause_threshold', value=3.0, approved=True)['ok']
    result = agent.command('Kaat, always add subtitles')
    assert result['ok'], result
    assert AgentController(path).state()['preferences'] == {'pause_threshold': 3.0, 'burn_subtitles': True}
    assert agent.command('Kaat, forget subtitle settings')['ok']
    assert AgentController(path).state()['preferences'] == {'pause_threshold': 3.0}


def test_explicit_target_rejection_does_not_change_selected_video(source, tmp_path):
    agent = AgentController(tmp_path / 'memory.sqlite3')
    assert agent.call('video.inspect', source=str(source))['ok']
    for utterance in ('Kaat, remove the last pause', 'Kaat, remove pauses and keep the first take'):
        result = agent.command(utterance)
        assert not result['ok'] and result['error']['message'] != 'No supported instruction recognized; no action taken.'
        assert agent.state()['cuts'] == [] and agent.state()['transcript'] == []


def test_detect_retakes_compound_executes_both_real_tools(source, tmp_path):
    agent = AgentController(tmp_path / 'memory.sqlite3')
    assert agent.call('video.inspect', source=str(source))['ok']
    text = 'Today we are explaining how this camera workflow operates.'
    assert agent.call('video.import_transcript', segments=[
        {'start': 0, 'end': 1, 'text': text, 'timing': 'segment'},
        {'start': 4, 'end': 5, 'text': text, 'timing': 'segment'},
    ])['ok']
    result = agent.command('Kaat, remove pauses and detect retakes')
    assert result['ok'], result
    assert [step['tool'] for step in result['operations']] == ['video.detect_pauses', 'video.detect_retakes']
    assert {cut['reason'] for cut in agent.state()['cuts']} == {'long_pause', 'possible_retake'}
    assert all(cut['status'] == 'suggested' for cut in agent.state()['cuts'])


def _two_tone_source(path):
    subprocess.run([
        _binary('ffmpeg'), '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=25:d=6',
        '-f', 'lavfi', '-i', r'aevalsrc=if(lt(t\,3)\,0.2*sin(2*PI*440*t)\,0.2*sin(2*PI*880*t)):s=16000:d=6',
        '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(path)
    ], check=True, capture_output=True)
    return path


@pytest.mark.parametrize('timing', ['chunk_only', 'segment', 'word'])
def test_partially_removed_captions_use_only_retained_audio(tmp_path, monkeypatch, timing):
    """Real audio extraction/render; the provider probe proves dataflow, not live ASR."""
    from array import array
    import math
    import wave
    source = _two_tone_source(tmp_path / 'two_tones.mp4')
    agent = AgentController(tmp_path / 'memory.sqlite3')
    assert agent.call('video.inspect', source=str(source))['ok']
    original_segments = [{'start': 0, 'end': 6, 'text': 'deleted first phrase retained second phrase', 'timing': timing}]
    assert agent.call('video.import_transcript', segments=original_segments)['ok']
    assert agent.call('video.propose_cut', start=0, end=3)['ok']
    assert agent.call('video.approve_all')['ok']
    submitted = []
    def provider_probe(audio, **kwargs):
        with wave.open(str(audio), 'rb') as wav:
            assert wav.getframerate() == 16000 and wav.getnchannels() == 1
            assert abs(wav.getnframes()/16000 - 3) < .001
            samples = array('h', wav.readframes(wav.getnframes()))
        samples = samples[8000:40000]
        def energy(frequency):
            real = sum(v*math.cos(2*math.pi*frequency*i/16000) for i,v in enumerate(samples))
            imag = sum(v*math.sin(2*math.pi*frequency*i/16000) for i,v in enumerate(samples))
            return real*real+imag*imag
        assert energy(880) > 100 * energy(440), 'Deleted 440 Hz audio reached the provider boundary'
        submitted.append(str(audio))
        return [{'start': 0, 'end': 3, 'text': 'unit fixture for retained tone only', 'timing': 'chunk_only'}]
    monkeypatch.setattr('voice.transcribe_pcm_wav', provider_probe)
    output = tmp_path / 'edited_captions.mp4'
    result = agent.call('video.export', output=str(output), subtitles=True)
    assert result['ok'], result
    assert result['data']['caption_source'] == 'edited_audio' and len(submitted) == 1
    text = output.with_suffix('.srt').read_text(encoding='utf-8')
    assert 'unit fixture for retained tone only' in text and 'deleted first phrase' not in text
    assert agent.state()['transcript'] == original_segments
    assert source_hash(source) == __import__('json').loads(output.with_suffix('.kaat-edl.json').read_text(encoding='utf-8'))['source_sha256']


def test_chunk_caption_export_without_key_leaves_no_false_caption_bundle(tmp_path, monkeypatch):
    monkeypatch.delenv('GNANI_API_KEY', raising=False)
    source = _two_tone_source(tmp_path / 'two_tones.mp4')
    agent = AgentController(tmp_path / 'memory.sqlite3')
    assert agent.call('video.inspect', source=str(source))['ok']
    assert agent.call('video.import_transcript', segments=[
        {'start': 0, 'end': 6, 'text': 'source chunk includes deleted material', 'timing': 'chunk_only'}])['ok']
    assert agent.call('video.propose_cut', start=0, end=3)['ok']
    assert agent.call('video.approve_all')['ok']
    output = tmp_path / 'not_exported.mp4'
    result = agent.call('video.export', output=str(output), subtitles=True)
    assert not result['ok'] and 'GNANI_API_KEY' in result['error']['message']
    assert not output.exists() and not output.with_suffix('.srt').exists() and not output.with_suffix('.kaat-edl.json').exists()


@pytest.mark.parametrize('timing', ['chunk_only', 'segment', 'word'])
def test_wholly_kept_or_removed_cues_remap_without_provider(tmp_path, monkeypatch, timing):
    """Whole cues have known text ownership; no invented intra-cue alignment is needed."""
    source = _two_tone_source(tmp_path / 'whole_cues.mp4')
    agent = AgentController(tmp_path / 'memory.sqlite3')
    assert agent.call('video.inspect', source=str(source))['ok']
    assert agent.call('video.import_transcript', segments=[
        {'start': 0, 'end': 3, 'text': 'deleted complete first cue', 'timing': timing},
        {'start': 3, 'end': 6, 'text': 'retained complete second cue', 'timing': timing},
    ])['ok']
    assert agent.call('video.propose_cut', start=0, end=3)['ok']
    assert agent.call('video.approve_all')['ok']
    def unnecessary_request(*args, **kwargs):
        pytest.fail('Fully retained/removed cue boundaries must not require an API call')
    monkeypatch.setattr('voice.transcribe_pcm_wav', unnecessary_request)
    output = tmp_path / 'mapped.mp4'
    result = agent.call('video.export', output=str(output), subtitles=True)
    assert result['ok'], result
    assert result['data']['caption_source'] == 'source_timestamps'
    text = output.with_suffix('.srt').read_text(encoding='utf-8')
    assert '00:00:00,000 --> 00:00:03,000' in text
    assert 'retained complete second cue' in text and 'deleted complete first cue' not in text
