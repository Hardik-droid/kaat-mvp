"""Independent media/speech-marker proof for cumulative-cut timing correctness.

All fixtures are controlled signals, not human speech. FFmpeg actually renders,
then separate decoding checks audio/video against an explicit numeric oracle.
"""
from array import array
import json
import math
import subprocess
import wave

import pytest

from engine import Cut, _binary, duration, extract_edit_audio, render, source_hash, write_srt


def ffmpeg(*args):
    return subprocess.run([_binary('ffmpeg'), '-nostdin', '-v', 'error', *map(str, args)],
                          check=True, capture_output=True, timeout=45)


def test_many_off_frame_cuts_preserve_actual_marker_and_subtitle_time(tmp_path):
    source = tmp_path / 'ten second marker.mkv'
    ffmpeg('-f', 'lavfi', '-i', r"color=c=black:s=320x240:r=25:d=10,drawbox=color=white:t=fill:enable='between(t,8.5,8.7)'",
           '-f', 'lavfi', '-i', r'aevalsrc=if(between(t\,8.5\,8.65)\,0.3*sin(2*PI*1000*t)\,0):s=48000:d=10',
           '-c:v', 'ffv1', '-c:a', 'pcm_s16le', source)
    fingerprint = source_hash(source)
    cuts = [Cut(.13+i*.4, .27+i*.4, 'approved timing probe', status='approved') for i in range(20)]
    edited = render(source, cuts, tmp_path / 'twenty cuts.mp4')
    # Independent oracle: twenty 140ms cuts occur before the source marker at8.5s.
    expected_duration = 10 - 20 * .14
    expected_marker = 8.5 - 20 * .14
    assert abs(duration(edited) - expected_duration) < .045
    assert source_hash(source) == fingerprint

    decoded = ffmpeg('-i', edited, '-map', '0:a:0', '-ac', 1, '-ar', 16000, '-f', 's16le', '-')
    samples = array('h', decoded.stdout)
    first_loud_sample = next(index for index, sample in enumerate(samples) if abs(sample) > 2000)
    assert abs(first_loud_sample / 16000 - expected_marker) < .025
    assert max(abs(value) for value in samples[round((expected_marker+.20)*16000):]) < 500

    # Decode actual retained frame timestamps, rather than trusting container duration.
    frames = json.loads(subprocess.run([
        _binary('ffprobe'), '-v', 'error', '-select_streams', 'v:0', '-show_entries',
        'frame=best_effort_timestamp_time', '-of', 'json', str(edited)
    ], check=True, capture_output=True).stdout)['frames']
    pixels = ffmpeg('-i', edited, '-map', '0:v:0', '-vf', 'scale=1:1', '-fps_mode', 'passthrough',
                    '-pix_fmt', 'rgb24', '-f', 'rawvideo', '-').stdout
    assert len(pixels) == 3 * len(frames)
    white_times = [float(frame['best_effort_timestamp_time']) for index, frame in enumerate(frames)
                   if min(pixels[index*3:index*3+3]) > 220]
    assert white_times and abs(white_times[0] - expected_marker) < .045
    assert abs(white_times[0] - first_loud_sample / 16000) < .045

    srt = write_srt([{'start':8.5, 'end':8.65, 'text':'The independently timed marker'}],
                    tmp_path / 'marker.srt', cuts=cuts, total=10)
    assert '00:00:05,700 --> 00:00:05,850' in srt.read_text(encoding='utf-8')


def test_video_only_many_cuts_uses_same_elapsed_timeline(tmp_path):
    source = tmp_path / 'video only.mkv'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=s=160x120:r=25:d=10', '-c:v', 'ffv1', source)
    cuts = [Cut(.13+i*.4, .27+i*.4, 'cut', status='approved') for i in range(20)]
    output = render(source, cuts, tmp_path / 'video only edited.mp4')
    assert abs(duration(output) - (10 - 20 * .14)) < .045


def test_edited_audio_contains_only_retained_content_and_source_padding(tmp_path):
    source = tmp_path / 'delayed two distinct takes.mkv'
    # Actual source audio occupies1–4s: first take440Hz, final take880Hz. The
    # independently defined approved cut removes first take and initial silence.
    ffmpeg('-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=25:d=5',
           '-itsoffset', 1, '-f', 'lavfi', '-i',
           r'aevalsrc=0.25*sin(2*PI*if(lt(t\,1.5)\,440\,880)*t):s=48000:d=3',
           '-c:v', 'ffv1', '-c:a', 'pcm_s16le', source)
    fingerprint = source_hash(source)
    destination = tmp_path / 'only final take.wav'
    output = extract_edit_audio(source, [Cut(0, 2.5, 'rejected take', status='approved'),
                                        Cut(2.6, 3.6, 'not approved')], destination)
    with wave.open(str(output), 'rb') as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, 16000)
        assert wav.getnframes() == 40000  # Source5s minus2.5s, including trailing absent audio.
        samples = array('h', wav.readframes(wav.getnframes()))
    def amplitude(frequency):
        chunk = samples[3200:6400]
        real = sum(value*math.cos(2*math.pi*frequency*i/16000) for i, value in enumerate(chunk))
        imag = sum(value*math.sin(2*math.pi*frequency*i/16000) for i, value in enumerate(chunk))
        return 2*math.hypot(real, imag)/len(chunk)
    assert amplitude(880) > 7000
    assert amplitude(440) < 50, 'The rejected take must not be supplied to the caption provider'
    assert max(abs(value) for value in samples[round(1.6*16000):]) < 10
    assert source_hash(source) == fingerprint
    with pytest.raises(FileExistsError):
        extract_edit_audio(source, [], destination)
    assert not list(tmp_path.glob('.kaat_audio_*'))


def test_edited_audio_refuses_source_overwrite_and_all_removed(tmp_path):
    source = tmp_path / 'source.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'color=c=black:s=160x120:r=25:d=1',
           '-f', 'lavfi', '-i', 'sine=frequency=440:duration=1',
           '-c:v', 'libx264', '-c:a', 'aac', source)
    fingerprint = source_hash(source)
    with pytest.raises(ValueError, match='original'):
        extract_edit_audio(source, [], source)
    with pytest.raises(ValueError, match='all audio'):
        extract_edit_audio(source, [Cut(0, 1, 'all', status='approved')], tmp_path/'removed.wav')
    assert source_hash(source) == fingerprint
    assert not (tmp_path/'removed.wav').exists()
