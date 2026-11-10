"""Non-destructive FFmpeg editing on the original media timeline."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass, field, replace
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable
from uuid import uuid4


@dataclass
class Cut:
    start: float
    end: float
    reason: str
    detail: str = ""
    status: str = "suggested"
    id: str = field(default_factory=lambda: uuid4().hex)

    def __post_init__(self):
        self.start, self.end = float(self.start), float(self.end)
        if not math.isfinite(self.start) or not math.isfinite(self.end) or self.end <= self.start:
            raise ValueError("A cut needs finite timestamps with end greater than start")
        if self.status not in {"suggested", "approved", "restored", "rejected"}:
            raise ValueError("Cut status must be suggested, approved, restored, or rejected")


def _binary(name: str) -> str:
    executable = shutil.which(os.environ.get(name.upper() + "_BINARY", name))
    if not executable:
        local = sorted((Path(__file__).parent / ".tools").glob(f"ffmpeg*/bin/{name}.exe"))
        if local:
            executable = str(local[0].resolve())
    if not executable:
        raise RuntimeError(f"{name} is missing. Install FFmpeg and add its bin folder to PATH.")
    return executable


def _ffmpeg():
    for name in ("ffmpeg", "ffprobe"):
        _binary(name)


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    result = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", **kwargs)
    if result.returncode:
        raise RuntimeError(f"{Path(args[0]).stem} failed: {result.stderr[-2500:]}")
    return result


def inspect_video(video: str | Path) -> dict:
    source = Path(video).expanduser().resolve(strict=True)
    if not source.is_file():
        raise ValueError("Select an existing video file")
    result = _run([_binary("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", str(source)])
    metadata = json.loads(result.stdout)
    streams = metadata.get("streams", [])
    if not any(s.get("codec_type") == "video" for s in streams):
        raise ValueError("The selected file has no video stream")
    container = metadata.get("format", {})
    origin = float(container.get("start_time", 0))
    total = float(container.get("duration", 0))
    if "matroska" in container.get("format_name", "").split(","):
        # Matroska stores the final timestamp; normalize it to elapsed source time.
        total -= origin
    if not math.isfinite(total) or total <= 0:
        raise ValueError("The selected video has no finite positive duration")
    return {"source": str(source), "duration_seconds": total, "streams": streams,
            "start_time": origin,
            "has_audio": any(s.get("codec_type") == "audio" for s in streams), "size_bytes": source.stat().st_size}


def duration(video: str | Path) -> float:
    return inspect_video(video)["duration_seconds"]


def find_pauses(video: str | Path, min_seconds: float = 2.0, threshold: str = "-40dB", pad: float = .18) -> list[Cut]:
    """Suggest amplitude-based gaps; never approve quiet speech for removal."""
    min_seconds, pad = float(min_seconds), float(pad)
    if not math.isfinite(min_seconds) or not .2 <= min_seconds <= 20:
        raise ValueError("Pause threshold must be between 0.2 and 20 seconds")
    if not math.isfinite(pad) or not 0 <= pad <= 2:
        raise ValueError("Silence padding must be between 0 and 2 seconds")
    if not re.fullmatch(r"-?\d+(?:\.\d+)?dB", threshold):
        raise ValueError("Noise threshold must be a decibel value such as -40dB")
    info = inspect_video(video)
    if not info["has_audio"]:
        raise ValueError("Silence detection requires an audio stream")
    total = info["duration_seconds"]
    result = _run([_binary("ffmpeg"), "-hide_banner", "-nostdin", "-i", info["source"], "-map", "0:a:0",
                   "-af", f"aresample=async=1:first_pts=0,apad,atrim=end={total:.9f},"
                   f"silencedetect=noise={threshold}:d={min_seconds}", "-f", "null", "-"])
    start, cuts = None, []
    for line in result.stderr.splitlines():
        match = re.search(r"silence_start:\s*([0-9.eE+-]+)", line)
        if match:
            start = max(0., float(match.group(1)))
        match = re.search(r"silence_end:\s*([0-9.eE+-]+)", line)
        if match and start is not None:
            end = min(total, float(match.group(1)))
            a, b = start + pad, end - pad
            if b > a:
                cuts.append(Cut(a, b, "long_pause", f"{end-start:.2f}s below {threshold}; review quiet speech"))
            start = None
    if start is not None and total - pad > start + pad:
        cuts.append(Cut(start + pad, total - pad, "long_pause", "Trailing silence; review before approval"))
    return cuts


def clean_text(value: str) -> str:
    text = re.sub(r"\bi['’]m\b", "i am", str(value).casefold())
    return " ".join(re.sub(r"[^\w\u0900-\u097F]+", " ", text).split())


def _segment(segment: dict) -> tuple[float, float, str]:
    start, end = float(segment["start"]), float(segment["end"])
    if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
        raise ValueError("Transcript segments require finite, increasing source timestamps")
    return start, end, clean_text(segment.get("text", ""))


def retake_suggestions(segments: list[dict], threshold: float = .87) -> list[Cut]:
    """Nearby repetitions are review suggestions, never automatically approved."""
    # ponytail: bounded stdlib similarity; verified alignment is needed for finer than chunk cuts.
    if not 0 < threshold <= 1:
        raise ValueError("Retake threshold must be between zero and one")
    ordered = sorted(segments, key=lambda segment: float(segment["start"]))
    parsed = [_segment(segment) for segment in ordered]
    found = []
    for i, (start, end, old_text) in enumerate(parsed):
        if len(old_text) < 24 or len(old_text.split()) < 5:
            continue
        for new_start, new_end, new_text in parsed[i + 1:i + 5]:
            if new_start < end or new_start - end > 90 or not new_text:
                continue
            ratio = SequenceMatcher(None, old_text, new_text).ratio()
            prefix = SequenceMatcher(None, old_text, new_text[:len(old_text)]).ratio()
            if ratio >= threshold or (prefix >= .92 and len(new_text) > len(old_text)):
                detail = f"similarity {max(ratio, prefix):.0%}; later take at {new_start:.2f}s; review"
                if ordered[i].get("timing") in {"chunk_only", "chunk_boundary"}:
                    detail += "; COARSE chunk spans may include unrelated speech"
                found.append(Cut(start, end, "possible_retake", detail))
                break
    return found


def _total(total: float) -> float:
    total = float(total)
    if not math.isfinite(total) or total <= 0:
        raise ValueError("Duration must be finite and positive")
    return total


def normalize(cuts: list[Cut], total: float) -> list[Cut]:
    """Union geometric intervals. Approval filtering happens before this function."""
    total = _total(total)
    valid = sorted((replace(c, start=max(0., c.start), end=min(total, c.end))
                    for c in cuts if c.end > 0 and c.start < total), key=lambda c: (c.start, c.end))
    merged: list[Cut] = []
    for cut in valid:
        if merged and cut.start <= merged[-1].end:
            last = merged[-1]
            last.end = max(last.end, cut.end)
            last.reason = "+".join(dict.fromkeys((last.reason + "+" + cut.reason).split("+")))
        else:
            merged.append(cut)
    return merged


def keep_ranges(total: float, cuts: list[Cut]) -> list[tuple[float, float]]:
    """Complement of approved cuts, including very short retained gaps."""
    total = _total(total)
    pos, output = 0., []
    for cut in normalize([c for c in cuts if c.status == "approved"], total):
        if cut.start > pos:
            output.append((pos, cut.start))
        pos = cut.end
    if total > pos:
        output.append((pos, total))
    return output


def source_hash(video: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(video).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fresh_output(video: str | Path | None, dest: str | Path) -> Path:
    target = Path(dest).expanduser().resolve()
    if video is not None and target == Path(video).expanduser().resolve():
        raise ValueError("Cannot overwrite original; choose a separate output filename")
    if target.exists() or target.is_symlink():
        raise FileExistsError("Output already exists; choose a fresh filename")
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def _publish(staged: Path, target: Path):
    # ponytail: atomic local NTFS/POSIX publication; filesystems without hard links fail safely.
    os.link(staged, target)


def _write_new(target: Path, text: str):
    with tempfile.TemporaryDirectory(prefix=".kaat_write_", dir=target.parent) as temp:
        staged = Path(temp) / "output"
        staged.write_text(text, encoding="utf-8")
        _publish(staged, target)


def save_plan(video: str | Path, cuts: list[Cut], dest: str | Path) -> dict:
    target = _fresh_output(video, dest)
    total = duration(video)
    kept = keep_ranges(total, cuts)
    data = {"version": 1, "source": str(Path(video).resolve()), "original": str(Path(video).resolve()),
            "source_sha256": source_hash(video), "original_duration": total,
            "edited_duration": round(sum(b - a for a, b in kept), 6),
            "operations": [{"type": "cut", **asdict(c)} for c in cuts],
            "cuts": [asdict(c) for c in cuts], "kept": kept,
            "source_untouched": True, "note": "Source timeline; only approved operations affect exports."}
    _write_new(target, json.dumps(data, indent=2, ensure_ascii=False))
    return data


def _srt_time(seconds: float) -> str:
    milliseconds = max(0, round(seconds * 1000))
    hours, rest = divmod(milliseconds, 3600000)
    minutes, rest = divmod(rest, 60000)
    seconds, milliseconds = divmod(rest, 1000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"


def write_srt(segments: list[dict], dest: str | Path, cuts: list[Cut] | None = None,
              total: float | None = None) -> Path:
    """Use supplied segment timestamps, optionally mapped to the approved edited timeline.

    Chunk transcripts remain whole chunk captions; word timestamps are never invented.
    """
    target = _fresh_output(None, dest)
    parsed = [(*_segment(segment)[:2], str(segment.get("text", "")).strip()) for segment in segments]
    if not parsed:
        raise ValueError("Transcribe speech before exporting subtitles")
    duration_seconds = _total(total if total is not None else max(end for start, end, text in parsed))
    ranges = keep_ranges(duration_seconds, cuts or [])
    captions, offset = [], 0.
    for kept_start, kept_end in ranges:
        for start, end, text in parsed:
            a, b = max(start, kept_start), min(end, kept_end)
            if b > a and text:
                captions.append((offset + a - kept_start, offset + b - kept_start,
                                 text.replace("\r", " ").replace("\n", " ").replace("-->", "→")))
        offset += kept_end - kept_start
    captions.sort(key=lambda caption: (caption[0], caption[1]))
    if not captions:
        raise ValueError("No nonempty transcript segments remain after approved cuts")
    _write_new(target, "\n".join(f"{i}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n"
                                for i, (a, b, text) in enumerate(captions, 1)))
    return target


def extract_edit_audio(video: str | Path, cuts: list[Cut], output_wav: str | Path) -> Path:
    """Render only the retained audio for a real post-edit caption transcription.

    Normalization and sample cuts match the video's audio path. This never needs
    video encoding and cannot carry removed speech into a new ASR request.
    """
    info = inspect_video(video)
    if not info["has_audio"]:
        raise ValueError("The selected video has no audio stream")
    target = _fresh_output(video, output_wav)
    if target.suffix.casefold() != ".wav":
        raise ValueError("Edited speech extraction requires a .wav output")
    ranges = keep_ranges(info["duration_seconds"], cuts)
    if not ranges:
        raise ValueError("The approved edits remove all audio")
    before = source_hash(info["source"])
    with tempfile.TemporaryDirectory(prefix=".kaat_audio_", dir=target.parent) as temp:
        work = Path(temp)
        graph = []
        for index, (start, end) in enumerate(ranges):
            graph.append(f"[0:a:0]aresample=async=1:first_pts=0,apad,"
                         f"atrim=start={start:.9f}:end={end:.9f},asetpts=PTS-STARTPTS[a{index}]")
        graph.append("".join(f"[a{index}]" for index in range(len(ranges)))
                     + f"concat=n={len(ranges)}:v=0:a=1[aout]")
        script = work / "audio_filters.txt"
        script.write_text(";\n".join(graph), encoding="utf-8")
        staged = work / "edited.wav"
        args = [_binary("ffmpeg"), "-nostdin", "-hide_banner", "-loglevel", "error",
                "-i", info["source"], "-/filter_complex", str(script), "-map", "[aout]",
                "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(staged)]
        try:
            _run(args, cwd=str(work))
        except RuntimeError as error:
            if "Unrecognized option '/filter_complex'" not in str(error):
                raise
            args[args.index("-/filter_complex")] = "-filter_complex_script"
            _run(args, cwd=str(work))
        if source_hash(info["source"]) != before:
            raise RuntimeError("Source changed during audio extraction; output withheld")
        _publish(staged, target)
    return target


def render(video: str | Path, cuts: list[Cut], output: str | Path,
           progress: Callable[[str], None] | None = None, subtitles: str | Path | None = None) -> Path:
    """Apply one source-time mapping to video and sample-accurate audio cuts.

    Audio/video concat pads each join to the longest rounded frame, so its error
    accumulates over many cuts. Keep the source video timestamps and subtract
    removed time once; concatenate audio separately without per-join video padding.
    """
    info = inspect_video(video)
    source, target = Path(info["source"]), _fresh_output(video, output)
    if target.suffix.casefold() != ".mp4":
        raise ValueError("Video exports must use the .mp4 extension")
    ranges = keep_ranges(info["duration_seconds"], cuts)
    if not ranges:
        raise ValueError("Edit would remove the entire video. Restore at least one cut.")
    before = source_hash(source)
    with tempfile.TemporaryDirectory(prefix=".kaat_render_", dir=target.parent) as temp:
        work = Path(temp)
        graph, audio_inputs = [], []
        video_stream = next(s for s in info["streams"] if s.get("codec_type") == "video")
        video_offset = max(0., float(video_stream.get("start_time", info["start_time"])) - info["start_time"])
        video_filters = (f"[0:v:0]setpts=PTS-STARTPTS,tpad=start_duration={video_offset:.9f}:start_mode=add,"
                         f"trim=end={info['duration_seconds']:.9f}")
        approved = normalize([cut for cut in cuts if cut.status == "approved"], info["duration_seconds"])
        if approved:
            excluded = "+".join(f"gte(t,{cut.start:.9f})*lt(t,{cut.end:.9f})" for cut in approved)
            elapsed = "+".join(f"{cut.end-cut.start:.9f}*gte(T,{cut.end:.9f})" for cut in approved)
            video_filters += f",select='not({excluded})',setpts='PTS-({elapsed})/TB'"
        graph.append(video_filters + "[vout]")
        for i, (start, end) in enumerate(ranges):
            if info["has_audio"]:
                # Fill a delayed/missing audio start before trimming so it stays aligned with video.
                graph.append(f"[0:a:0]aresample=async=1:first_pts=0,apad,"
                             f"atrim=start={start:.9f}:end={end:.9f},asetpts=PTS-STARTPTS[a{i}]")
                audio_inputs.append(f"[a{i}]")
        if audio_inputs:
            graph.append("".join(audio_inputs) + f"concat=n={len(ranges)}:v=0:a=1[aout]")
        # H.264/yuv420p needs even dimensions; retain odd screen captures with 1px padding.
        graph.append("[vout]pad=ceil(iw/2)*2:ceil(ih/2)*2[vpad]")
        video_label = "[vpad]"
        if subtitles is not None:
            shutil.copyfile(Path(subtitles).resolve(strict=True), work / "captions.srt")
            graph.append("[vpad]subtitles=filename=captions.srt[vsub]")
            video_label = "[vsub]"
        script = work / "filters.txt"
        script.write_text(";\n".join(graph), encoding="utf-8")
        staged = work / "rendered.mp4"
        args = [_binary("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(source),
                "-/filter_complex", str(script), "-map", video_label]
        if info["has_audio"]:
            args += ["-map", "[aout]", "-c:a", "aac", "-b:a", "160k"]
        args += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-pix_fmt", "yuv420p",
                 "-fps_mode", "vfr", "-enc_time_base:v", video_stream.get("time_base", "1/90000"),
                 "-movflags", "+faststart", str(staged)]
        if progress:
            progress(f"Rendering {len(ranges)} retained ranges; source remains untouched")
        try:
            _run(args, cwd=str(work))
        except RuntimeError as error:
            if "Unrecognized option '/filter_complex'" not in str(error):
                raise
            # FFmpeg 6 and earlier use the legacy name; FFmpeg 9 removed that alias.
            args[args.index("-/filter_complex")] = "-filter_complex_script"
            _run(args, cwd=str(work))
        # A selection can retain audio but no actual video frame; never publish
        # an audio-only file as a successful video export.
        inspect_video(staged)
        if source_hash(source) != before:
            raise RuntimeError("Source changed during rendering; export withheld")
        _publish(staged, target)
    if progress:
        progress("Edited MP4 saved; original SHA256 verified unchanged")
    return target


def prisma_transcribe(video: str | Path) -> list[dict]:
    """Compatibility entry point for the shared Gnani voice engine."""
    from voice import transcribe_video
    return transcribe_video(video)
