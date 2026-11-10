"""Generated-media checks: approval, interval math, sync, captions, source protection."""
import json
import os
import subprocess
from array import array

import pytest

from engine import (Cut, _binary, duration, find_pauses, inspect_video, keep_ranges,
                    normalize, render, retake_suggestions, save_plan, source_hash, write_srt)


@pytest.fixture(scope="module")
def sample(tmp_path_factory):
    root = tmp_path_factory.mktemp("media")
    source = root / "original ' Hinglish.mp4"
    try:
        ffmpeg = _binary("ffmpeg")
        _binary("ffprobe")
    except RuntimeError as error:
        pytest.skip(str(error))
    subprocess.run([
        ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "color=c=navy:s=320x240:r=30:d=4.5",
        "-f", "lavfi", "-i",
        r"aevalsrc=if(between(t\,1\,3.5)\,0\,0.15*sin(2*PI*440*t)):s=48000:d=4.5",
        "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
    ], check=True, capture_output=True)
    return source


def approved(start, end, reason="user_approved"):
    return Cut(start, end, reason, status="approved")


def test_intervals_union_and_approval():
    proposed = Cut(1, 9, "unapproved")
    cuts = [approved(3, 6), approved(5, 7), approved(100, 101), proposed]
    union = normalize(cuts[:3], 10)
    assert [(c.start, c.end) for c in union] == [(3, 7)]
    assert keep_ranges(10, cuts) == [(0., 3), (7, 10)]
    assert proposed.status == "suggested"


def test_normalize_clips_negative_and_outside_intervals():
    cuts = [approved(-2, 2), approved(9, 15), approved(-9, -2)]
    assert keep_ranges(10, cuts) == [(2, 9)]


def test_very_short_keep_is_not_silently_removed():
    assert keep_ranges(10, [approved(0, 4), approved(4.01, 10)]) == [(4, 4.01)]


@pytest.mark.parametrize("start,end", [(float("nan"), 2), (1, float("inf")), (2, 1), (1, 1)])
def test_invalid_cut_is_rejected(start, end):
    with pytest.raises(ValueError):
        Cut(start, end, "invalid")


def test_retake_keep_last_is_suggestion():
    segments = [
        {"start": 0, "end": 5, "text": "hello friends today we are reviewing five tools"},
        {"start": 5, "end": 7, "text": "sorry"},
        {"start": 7, "end": 12, "text": "hello friends today we are reviewing five tools"},
    ]
    cuts = retake_suggestions(segments)
    assert len(cuts) == 1 and cuts[0].start == 0
    assert cuts[0].status == "suggested"
    assert keep_ranges(12, cuts) == [(0., 12)]


def test_retake_temporal_proximity_and_abandoned_prefix():
    segments = [
        {"start": 0, "end": 4, "text": "today we are going to explain"},
        {"start": 5, "end": 10, "text": "today we are going to explain how AI works"},
        {"start": 200, "end": 204, "text": "today we are going to explain"},
    ]
    cuts = retake_suggestions(segments)
    assert len(cuts) == 1 and cuts[0].end == 4


def test_coarse_retake_warns_about_chunk_span():
    segments = [
        {"start": 0, "end": 25, "text": "hello friends today we are reviewing five tools", "timing": "chunk_only"},
        {"start": 25, "end": 50, "text": "hello friends today we are reviewing five tools", "timing": "chunk_only"},
    ]
    assert "COARSE" in retake_suggestions(segments)[0].detail


def test_contracted_repeat_after_abandoned_sentence():
    segments = [{"start": 0, "end": 4, "text": "Today I am going to explain..."},
                {"start": 5, "end": 9, "text": "Today I'm going to explain how AI works."}]
    assert len(retake_suggestions(segments)) == 1


def test_srt_maps_only_approved_cuts(tmp_path):
    segments = [
        {"start": 0, "end": 2, "text": "Hello dosto"},
        {"start": 4, "end": 6, "text": "Aaj AI seekhenge"},
    ]
    path = write_srt(segments, tmp_path / "edited.srt",
                     cuts=[approved(2, 4), Cut(4, 6, "unapproved")], total=6)
    text = path.read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:02,000" in text
    assert "00:00:02,000 --> 00:00:04,000" in text
    assert "Aaj AI seekhenge" in text
    with pytest.raises(FileExistsError):
        write_srt(segments, path)


def test_sample_inspection_and_real_silence(sample):
    info = inspect_video(sample)
    assert info["has_audio"] and abs(info["duration_seconds"] - 4.5) < .1
    cuts = find_pauses(sample)
    assert len(cuts) == 1
    assert 1.1 < cuts[0].start < 1.3 and 3.2 < cuts[0].end < 3.4
    assert cuts[0].status == "suggested"


def test_render_approved_only_sync_and_source_preservation(sample, tmp_path):
    before = source_hash(sample)
    cuts = find_pauses(sample)
    cuts[0].status = "approved"
    cuts.append(Cut(0, 1, "unapproved speech"))
    output = render(sample, cuts, tmp_path / "edited ' copy.mp4")
    assert source_hash(sample) == before
    expected = sum(b - a for a, b in keep_ranges(duration(sample), cuts))
    info = inspect_video(output)
    assert abs(info["duration_seconds"] - expected) < .12
    stream_durations = [float(s["duration"]) for s in info["streams"] if s["codec_type"] in {"video", "audio"}]
    assert len(stream_durations) == 2 and max(stream_durations) - min(stream_durations) < .08
    plan = save_plan(sample, cuts, tmp_path / "edl.json")
    assert plan["source_sha256"] == before and plan["source_untouched"]
    assert [operation["status"] for operation in plan["operations"]] == ["approved", "suggested"]
    assert json.loads((tmp_path / "edl.json").read_text())["edited_duration"] == round(expected, 6)


def test_unapproved_export_preserves_entire_duration(sample, tmp_path):
    output = render(sample, [Cut(0, 3, "not approved")], tmp_path / "unedited.mp4")
    assert abs(duration(output) - duration(sample)) < .1


def test_subtitle_burn_uses_actual_ffmpeg(sample, tmp_path):
    captions = write_srt([{"start": 0, "end": 4.5, "text": "Hello dosto, this is KAAT"}],
                         tmp_path / "captions.srt")
    output = render(sample, [], tmp_path / "subtitled.mp4", subtitles=captions)
    assert output.exists() and abs(duration(output) - 4.5) < .1


def test_source_output_alias_and_existing_files_are_protected(sample, tmp_path):
    before = source_hash(sample)
    with pytest.raises(ValueError):
        render(sample, [], sample)
    with pytest.raises(ValueError):
        save_plan(sample, [], sample)
    alias = tmp_path / "alias.mp4"
    os.link(sample, alias)
    with pytest.raises(FileExistsError):
        render(sample, [], alias)
    output = tmp_path / "exists.mp4"
    output.write_bytes(b"unrelated data")
    with pytest.raises(FileExistsError):
        render(sample, [], output)
    with pytest.raises(FileExistsError):
        save_plan(sample, [], output)
    assert output.read_bytes() == b"unrelated data" and source_hash(sample) == before


def test_full_removal_is_rejected_without_output(sample, tmp_path):
    output = tmp_path / "empty.mp4"
    with pytest.raises(ValueError, match="entire video"):
        render(sample, [approved(0, 20)], output)
    assert not output.exists()


def test_video_without_audio_can_export(tmp_path):
    ffmpeg = _binary("ffmpeg")
    source = tmp_path / "silent.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=160x120:r=25:d=1", "-c:v", "libx264", str(source)],
                   check=True, capture_output=True)
    with pytest.raises(ValueError, match="audio stream"):
        find_pauses(source)
    output = render(source, [approved(.25, .5)], tmp_path / "silent-edited.mp4")
    assert not inspect_video(output)["has_audio"] and abs(duration(output) - .76) < .08


def test_delayed_audio_start_stays_in_sync(tmp_path):
    ffmpeg = _binary("ffmpeg")
    source = tmp_path / "offset-audio.mp4"
    subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i",
                    "color=c=black:s=160x120:r=25:d=2", "-itsoffset", "0.5", "-f", "lavfi", "-i",
                    "sine=frequency=440:sample_rate=48000:duration=1.5", "-c:v", "libx264", "-c:a", "aac",
                    str(source)], check=True, capture_output=True)
    output = render(source, [approved(.8, 1)], tmp_path / "offset-edited.mp4")
    decoded = subprocess.run([ffmpeg, "-hide_banner", "-loglevel", "error", "-i", str(output),
                              "-map", "0:a:0", "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                             check=True, capture_output=True)
    pcm = array("h", decoded.stdout)
    assert max(abs(n) for n in pcm[:4800]) < 50
    assert max(abs(n) for n in pcm[9600:11200]) > 1000
