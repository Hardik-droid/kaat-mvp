"""Small independent checks for the live report's reference-error calculation."""
from scripts.check_prisma_real import word_error_rate
from array import array
from pathlib import Path
import math
import subprocess
import wave

import pytest

import voice
from engine import _binary


def test_real_report_counts_missing_and_wrong_words_instead_of_only_nonempty_text():
    result = word_error_rate('इस tutorial में आपका स्वागत है', 'इस tutorial में स्वागत था')
    assert result['errors'] == 2
    assert result['reference_words'] == 6
    assert result['wer'] == 2/6
    assert word_error_rate('formatting', 'फॉर्मेटिंग')['wer'] == 1


def test_real_report_normalizes_punctuation_but_does_not_invent_roman_alignment():
    assert word_error_rate('यह, Tutorial है।', 'यह tutorial है')['errors'] == 0
    assert word_error_rate('a b', 'a b c')['wer'] == .5


def test_push_to_talk_requests_roman_hinglish_at_provider_boundary(monkeypatch):
    # Unit contract check only: real provider results are reported separately.
    observed = []
    monkeypatch.setattr(voice, '_client', lambda: object())
    monkeypatch.setattr(voice, 'capture_command_audio', lambda seconds: array('h', [1000]*1600).tobytes())
    def boundary(path, **kwargs):
        observed.append((Path(path), kwargs))
        assert Path(path).exists()
        return {'text': 'Kaat, pauses hata de'}
    monkeypatch.setattr(voice, 'transcribe_audio', boundary)
    assert voice.hear_command() == 'Kaat, pauses hata de'
    assert observed[0][1] == {'output_format': 'transliterate'}
    assert not observed[0][0].exists()


@pytest.mark.parametrize('extension,delay,offset', [('mp4', 1, 0), ('mkv', 1, 5), ('mkv', 26, 0), ('mkv', 1, -.5)])
def test_real_chunk_pcm_keeps_delayed_and_short_audio_on_source_timeline(tmp_path, monkeypatch, extension, delay, offset):
    """Real FFmpeg PCM evidence; provider is replaced solely to inspect extraction."""
    source = tmp_path / ('delayed.' + extension)
    audio_duration = 25 if delay == 1 else 1
    args = [_binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
            '-f', 'lavfi', '-i', 'color=c=navy:s=64x64:r=10:d=27',
            '-itsoffset', str(delay), '-f', 'lavfi', '-i',
            f'sine=frequency=440:sample_rate=16000:duration={audio_duration}',
            '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac' if extension == 'mp4' else 'pcm_s16le']
    if offset:
        args += ['-output_ts_offset', str(offset)]
    subprocess.run(args + [str(source)], check=True, capture_output=True)
    captured = []
    def boundary(path, **kwargs):
        with wave.open(str(path), 'rb') as wav:
            captured.append((wav.getframerate(), array('h', wav.readframes(wav.getnframes()))))
        return {'text': 'UNIT ONLY: real audio extracted; provider was not called'}
    monkeypatch.setattr(voice, '_client', lambda: object())
    monkeypatch.setattr(voice, 'transcribe_audio', boundary)
    chunks = voice.transcribe_video(source)
    assert [(c['start'], c['end']) for c in chunks] == [(0, 25), (25, 27)]
    assert len(captured[0][1]) == 25 * 16000 and len(captured[1][1]) == 2 * 16000
    def rms(index, start, end):
        samples = captured[index][1][round(start*16000):round(end*16000)]
        return math.sqrt(sum(n*n for n in samples)/len(samples))
    assert rms(0, 0, .5) < 1
    if delay == 1:
        assert rms(0, 1.5, 2) > 1000
        assert rms(1, .2, .6) > 1000
        assert rms(1, 1.5, 1.9) < 1
    else:
        assert rms(0, 23, 24) < 1
        assert rms(1, .1, .5) < 1
        assert rms(1, 1.3, 1.8) > 1000


def test_negative_container_start_cannot_fastseek_past_audio_at_video_keyframes(tmp_path, monkeypatch):
    source = tmp_path / 'negative.mkv'
    subprocess.run([_binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', 'color=c=navy:s=64x64:r=10:d=50',
        '-f', 'lavfi', '-i', 'sine=frequency=440:sample_rate=16000:duration=50',
        '-c:v', 'libx264', '-c:a', 'pcm_s16le', '-output_ts_offset', '-0.5',
        '-avoid_negative_ts', 'disabled', str(source)], check=True, capture_output=True)
    from engine import inspect_video
    assert inspect_video(source)['start_time'] == -.5
    assert inspect_video(source)['duration_seconds'] == 50
    captured = []
    def boundary(path, **kwargs):
        with wave.open(str(path), 'rb') as wav:
            captured.append(array('h', wav.readframes(wav.getnframes())))
        return {'text': 'UNIT ONLY: no provider request'}
    monkeypatch.setattr(voice, '_client', lambda: object())
    monkeypatch.setattr(voice, 'transcribe_audio', boundary)
    chunks = voice.transcribe_video(source)
    assert [(c['start'], c['end']) for c in chunks] == [(0, 25), (25, 50)]
    for samples in captured:
        assert len(samples) == 400000
        for second in (.5, 20):
            window = samples[round(second*16000):round((second+.5)*16000)]
            assert math.sqrt(sum(n*n for n in window)/len(window)) > 1000
