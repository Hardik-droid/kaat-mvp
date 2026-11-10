"""Real FFmpeg regressions verified by decoding frames and PCM, never mock renders.

Fixtures are deliberately generated signals. They test media correctness, not
human speech recognition, and are kept short enough to run on a normal laptop.
"""
from array import array
import math
from pathlib import Path
import subprocess

import pytest

from engine import Cut, _binary, duration, find_pauses, inspect_video, render, source_hash, write_srt


def ffmpeg(*args):
    return subprocess.run([_binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin", *map(str, args)],
                          check=True, capture_output=True, timeout=40)


@pytest.fixture(scope="module")
def sequence(tmp_path_factory):
    root = tmp_path_factory.mktemp("practical_media")
    source = root / "source colours and stereo.mp4"
    colours = ";".join(f"color=c={colour}:s=160x120:r=25:d=1[c{i}]"
                       for i, colour in enumerate(("red", "green", "blue", "yellow")))
    colours += ";[c0][c1][c2][c3]concat=n=4:v=1:a=0"
    left = r"0.2*sin(2*PI*if(lt(t\,1)\,440\,if(lt(t\,2)\,660\,if(lt(t\,3)\,880\,1100)))*t)"
    audio = "aevalsrc=" + left + r"|0.1*sin(2*PI*1230*t):s=48000:d=4:c=stereo"
    ffmpeg("-f", "lavfi", "-i", colours, "-f", "lavfi", "-i", audio,
           "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", source)
    return source


def frame_rgb(path, seconds):
    result = ffmpeg("-ss", seconds, "-i", path, "-map", "0:v:0", "-frames:v", "1",
                    "-vf", "scale=1:1", "-pix_fmt", "rgb24", "-f", "rawvideo", "-")
    assert len(result.stdout) == 3, "A retained video frame must actually decode"
    return tuple(result.stdout)


def pcm_channels(path, channels=2):
    decoded = ffmpeg("-i", path, "-map", "0:a:0", "-ac", channels, "-ar", 16000, "-f", "s16le", "-")
    samples = array("h", decoded.stdout)
    return [samples[index::channels] for index in range(channels)]


def amplitude(samples, frequency, seconds):
    window = samples[round(seconds * 16000):round((seconds + .15) * 16000)]
    assert len(window) == 2400
    real = sum(value * math.cos(2 * math.pi * frequency * i / 16000) for i, value in enumerate(window))
    imag = sum(value * math.sin(2 * math.pi * frequency * i / 16000) for i, value in enumerate(window))
    return 2 * math.hypot(real, imag) / len(window)


def test_decoded_frames_and_stereo_content_follow_approved_union(sequence, tmp_path):
    before = source_hash(sequence)
    cuts = [Cut(.8, 1.7, "first", status="approved"), Cut(1.5, 2.2, "overlap", status="approved"),
            Cut(0, .7, "unapproved speech")]
    output = render(sequence, cuts, tmp_path / "colours edited.mp4")
    assert source_hash(sequence) == before
    assert abs(duration(output) - 2.6) < .08
    red, blue, yellow = (frame_rgb(output, t) for t in (.3, 1.1, 2.1))
    assert red[0] > 200 and max(red[1:]) < 30
    assert blue[2] > 200 and max(blue[:2]) < 30
    assert min(yellow[:2]) > 200 and yellow[2] < 30
    left, right = pcm_channels(output)
    # Independent signal measurements check the actual audio at the same moments.
    for second, expected in ((.2, 440), (1.05, 880), (2.0, 1100)):
        assert amplitude(left, expected, second) > 4000
        assert amplitude(right, 1230, second) > 1800
        assert amplitude(right, expected, second) < 250
    streams = inspect_video(output)["streams"]
    assert next(s for s in streams if s["codec_type"] == "audio")["channels"] == 2


@pytest.mark.parametrize("offset", [5, -.5])
def test_matroska_nonzero_timestamps_use_elapsed_duration(sequence, tmp_path, offset):
    source = tmp_path / f"offset {offset}.mkv"
    # Matroska's duration is an end timestamp when its start is nonzero.
    ffmpeg("-i", sequence, "-c:v", "copy", "-c:a", "pcm_s16le",
           "-output_ts_offset", offset, "-avoid_negative_ts", "disabled", source)
    before = source_hash(source)
    source_audio = pcm_channels(source)
    actual_elapsed = len(source_audio[0]) / 16000
    assert abs(actual_elapsed - 4) < .04
    assert abs(duration(source) - actual_elapsed) < .06
    output = render(source, [Cut(1, 2, "one second", status="approved")], tmp_path / "offset-edited.mp4")
    assert source_hash(source) == before
    assert abs(duration(output) - (actual_elapsed - 1)) < .08
    left, right = pcm_channels(output)
    assert abs(len(left) / 16000 - 3) < .08
    assert amplitude(left, 440, .1) > 3500
    assert amplitude(left, 880, 1.1) > 3500
    assert amplitude(right, 1230, 1.1) > 1800


def test_odd_sized_valid_video_exports_with_minimal_padding(tmp_path):
    source = tmp_path / "odd-sized screen recording.mkv"
    ffmpeg("-f", "lavfi", "-i", "testsrc=s=161x121:r=25:d=1", "-c:v", "ffv1", source)
    before = source_hash(source)
    output = render(source, [], tmp_path / "even-mp4.mp4")
    info = inspect_video(output)
    stream = next(s for s in info["streams"] if s["codec_type"] == "video")
    assert (stream["width"], stream["height"]) == (162, 122)
    assert abs(info["duration_seconds"] - 1) < .04
    assert source_hash(source) == before


def test_rotated_portrait_recording_preserves_display_orientation(tmp_path):
    raw = tmp_path / "portrait.mp4"
    source = tmp_path / "phone rotation.mp4"
    ffmpeg("-f", "lavfi", "-i", "testsrc2=s=120x200:r=25:d=2", "-c:v", "libx264", raw)
    ffmpeg("-display_rotation:v:0", "90", "-i", raw, "-c", "copy", source)
    metadata = inspect_video(source)["streams"][0].get("side_data_list", [])
    assert any(side.get("rotation") == 90 for side in metadata), "Fixture must contain a real display matrix"
    output = render(source, [Cut(.8, 1.2, "test", status="approved")], tmp_path / "rotated-edit.mp4")
    stream = next(s for s in inspect_video(output)["streams"] if s["codec_type"] == "video")
    assert (stream["width"], stream["height"]) == (200, 120)
    def pixels(path):
        return ffmpeg("-ss", .2, "-i", path, "-frames:v", "1", "-vf", "scale=40:40",
                      "-pix_fmt", "rgb24", "-f", "rawvideo", "-").stdout
    original, edited = pixels(source), pixels(output)
    assert len(original) == len(edited) == 4800
    assert sum(abs(a - b) for a, b in zip(original, edited)) / 4800 < 8


def test_variable_frame_rate_keeps_content_and_audio_on_timeline(sequence, tmp_path):
    source = tmp_path / "variable-rate.mp4"
    ffmpeg("-i", sequence, "-vf", r"select=if(lt(t\,2)\,not(mod(n\,3))\,1)",
           "-fps_mode", "vfr", "-c:v", "libx264", "-c:a", "copy", source)
    output = render(source, [Cut(.8, 2.2, "test", status="approved")], tmp_path / "vfr-edit.mp4")
    assert abs(duration(output) - 2.6) < .12
    red, blue = frame_rgb(output, .3), frame_rgb(output, 1.1)
    assert red[0] > 200 and red[2] < 30
    assert blue[2] > 200 and blue[0] < 30
    assert amplitude(pcm_channels(output)[0], 880, 1.1) > 3500


def test_no_video_frame_retained_fails_visibly_and_leaves_no_output(sequence, tmp_path):
    output = tmp_path / "sub-frame-edit.mp4"
    before = source_hash(sequence)
    with pytest.raises((RuntimeError, ValueError)):
        render(sequence, [Cut(0, .01, "test", status="approved"), Cut(.02, 4, "test", status="approved")], output)
    assert not output.exists() and source_hash(sequence) == before
    assert not list(tmp_path.glob(".kaat_render_*"))


def test_missing_subtitle_and_corrupt_video_never_publish_partial_output(sequence, tmp_path):
    before = source_hash(sequence)
    output = tmp_path / "missing-captions.mp4"
    with pytest.raises(FileNotFoundError):
        render(sequence, [], output, subtitles=tmp_path / "missing.srt")
    assert not output.exists() and source_hash(sequence) == before
    assert not list(tmp_path.glob(".kaat_render_*"))
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_bytes(b"not a video")
    with pytest.raises(RuntimeError):
        render(corrupt, [], tmp_path / "invalid.mp4")
    assert not (tmp_path / "invalid.mp4").exists()


def test_missing_leading_and_trailing_audio_is_detected_on_video_timeline(tmp_path):
    source = tmp_path / "audio present only from one to three.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=160x120:r=25:d=4",
           "-itsoffset", 1, "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=2",
           "-c:v", "libx264", "-c:a", "aac", source)
    cuts = find_pauses(source, min_seconds=.5)
    assert len(cuts) == 2, "Actual absent audio at both ends is silence, not spoken content"
    assert cuts[0].start == pytest.approx(.18, abs=.03)
    assert cuts[0].end == pytest.approx(.82, abs=.05)
    assert cuts[1].start == pytest.approx(3.18, abs=.05)
    assert cuts[1].end == pytest.approx(3.82, abs=.03)
    assert all(cut.status == "suggested" for cut in cuts)


def test_one_silent_stereo_channel_does_not_remove_other_channel_speech(tmp_path):
    source = tmp_path / "single active microphone channel.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=red:s=160x120:r=25:d=3",
           "-f", "lavfi", "-i", "aevalsrc=0.2*sin(2*PI*440*t)|0:s=48000:d=3:c=stereo",
           "-c:v", "libx264", "-c:a", "aac", source)
    assert find_pauses(source, min_seconds=.5) == []


def test_delayed_video_start_keeps_black_gap_and_audio_alignment(tmp_path):
    source = tmp_path / "camera started after microphone.mkv"
    ffmpeg("-itsoffset", 1, "-f", "lavfi", "-i", "color=c=red:s=160x120:r=25:d=2",
           "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000:duration=3",
           "-c:v", "libx264", "-c:a", "pcm_s16le", source)
    output = render(source, [], tmp_path / "delayed-video.mp4")
    assert abs(duration(output) - 3) < .08
    assert max(frame_rgb(output, .3)) < 10
    red = frame_rgb(output, 1.3)
    assert red[0] > 200 and max(red[1:]) < 30
    assert amplitude(pcm_channels(output, channels=1)[0], 440, .2) > 2500


def test_burned_captions_change_visible_lower_frame_pixels_only(tmp_path):
    source = tmp_path / "uniform dark background.mp4"
    ffmpeg("-f", "lavfi", "-i", "color=c=black:s=480x270:r=25:d=2",
           "-c:v", "libx264", "-pix_fmt", "yuv420p", source)
    captions = write_srt([{"start": .2, "end": 1.8, "text": "KAAT caption is visibly burned"}],
                         tmp_path / "verified timing.srt")
    baseline = render(source, [], tmp_path / "without-caption.mp4")
    subtitled = render(source, [], tmp_path / "with-caption.mp4", subtitles=captions)
    def pixels(path):
        decoded = ffmpeg("-ss", 1, "-i", path, "-frames:v", 1, "-pix_fmt", "rgb24", "-f", "rawvideo", "-")
        assert len(decoded.stdout) == 480 * 270 * 3
        return decoded.stdout
    plain, burned = pixels(baseline), pixels(subtitled)
    # Encoder noise cannot explain a connected group of white caption pixels.
    top = 480 * 150 * 3
    assert max(abs(a - b) for a, b in zip(plain[:top], burned[:top])) < 8
    lower_plain, lower_burned = plain[top:], burned[top:]
    bright_new_pixels = sum(1 for index in range(0, len(lower_plain), 3)
                            if min(lower_burned[index:index+3]) > 180
                            and max(lower_plain[index:index+3]) < 30)
    assert bright_new_pixels > 100, "The exported video must contain actual visible subtitle glyphs"
