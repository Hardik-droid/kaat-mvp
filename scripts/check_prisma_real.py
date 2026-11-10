"""Bounded, actual Prisma checks on two public human Hinglish recordings.

Makes three provider requests and writes measured transcripts/errors, never a
fabricated ASR pass. No microphone is activated. Audio and evidence stay under
the chosen ignored output directory, separate from the source release.
Use --prepare-only to download and build the fixture without a key or API calls.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import unicodedata
import wave

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from commands import parse_command
from voice import transcribe_audio

DATASET = "dianavdavidson/MUCS-Hinglish"
UPSTREAM = "https://www.openslr.org/104/"
MIRROR = "https://huggingface.co/datasets/" + DATASET
ROWS = "https://datasets-server.huggingface.co/rows"


def words(text):
    """Keep scripts distinct: transliterated spelling differences count as errors."""
    text = unicodedata.normalize("NFC", text).casefold()
    return re.sub(r"[^\w\s\u0900-\u097F]", " ", text).replace("।", " ").split()


def word_error_rate(reference, hypothesis):
    expected, actual = words(reference), words(hypothesis)
    previous = list(range(len(actual) + 1))
    for i, expected_word in enumerate(expected, 1):
        current = [i]
        for j, actual_word in enumerate(actual, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j-1] + (expected_word != actual_word)))
        previous = current
    return {"errors": previous[-1], "reference_words": len(expected),
            "wer": previous[-1] / len(expected) if expected else None,
            "normalization": "NFC, case/punctuation/whitespace only; scripts/spelling remain distinct"}


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def safe_error(error):
    message = str(error)
    key = os.getenv("GNANI_API_KEY", "")
    return message.replace(key, "[redacted]") if key else message


def build_fixture(samples, output):
    """Prepare actual human audio with a controlled gap; no speech API call."""
    from engine import _binary, duration, find_pauses
    video = output / 'human_hinglish_with_pause.mp4'
    total = sum(sample['seconds'] for sample in samples) + 3.2
    subprocess.run([_binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
        '-f', 'lavfi', '-i', f'testsrc2=size=640x360:rate=25:duration={total:.6f}',
        '-i', samples[0]['path'], '-f', 'lavfi', '-i', 'anullsrc=r=16000:cl=mono:d=3.2',
        '-i', samples[1]['path'], '-filter_complex', '[1:a][2:a][3:a]concat=n=3:v=0:a=1[a]',
        '-map', '0:v', '-map', '[a]', '-shortest', '-c:v', 'libx264', '-preset', 'veryfast',
        '-crf', '22', '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(video)],
        check=True, capture_output=True, timeout=90)
    subprocess.run([_binary('ffmpeg'), '-nostdin', '-hide_banner', '-loglevel', 'error',
                    '-i', str(video), '-f', 'null', '-'], check=True, capture_output=True, timeout=60)
    cuts = find_pauses(video)
    if not cuts:
        raise RuntimeError('Prepared public-speech fixture has no detectable controlled pause')
    fixture = {'video': str(video), 'duration': duration(video), 'sha256': sha256(video),
        'source_audio': 'Two genuine human Hindi-English MUCS lecture recordings',
        'video_track': 'Generated FFmpeg test pattern; not a filmed human video',
        'sources': samples, 'source_links': [UPSTREAM, MIRROR], 'license': 'Original corpus CC BY-SA 4.0; audio excluded from source release',
        'inserted_silence_seconds': 3.2, 'expected_silence_source_interval': [samples[0]['seconds'], samples[0]['seconds']+3.2],
        'detected_suggested_cuts': [cut.__dict__ for cut in cuts], 'decode_succeeded': True,
        'prisma_calls_during_preparation': 0, 'microphone_used': False}
    (output/'video_fixture.json').write_text(json.dumps(fixture, ensure_ascii=False, indent=2), encoding='utf-8')
    return fixture


def run(output, prepare_only=False):
    if not prepare_only and not os.getenv("GNANI_API_KEY", "").strip():
        raise RuntimeError("GNANI_API_KEY is required for this actual-provider check")
    output = Path(output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    report_path = output / "report.json"
    if report_path.exists():
        raise FileExistsError("A report already exists; choose a fresh output folder")
    response = requests.get(ROWS, params={"dataset": DATASET, "config": "default", "split": "test",
                                         "offset": 0, "length": 2}, timeout=30)
    response.raise_for_status()
    metadata = response.json()
    (output / "dataset_rows.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    samples = []
    for entry in metadata["rows"]:
        row = entry["row"]
        audio = output / (row["segment_id"] + ".wav")
        if not audio.exists():
            download = requests.get(row["audio"][0]["src"], timeout=30)
            download.raise_for_status()
            audio.write_bytes(download.content)
        with wave.open(str(audio), "rb") as wav:
            seconds = wav.getnframes() / wav.getframerate()
            if not 0 < seconds <= 30 or wav.getframerate() != 16000 or wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise RuntimeError("Dataset sample does not meet the advertised bounded 16 kHz format")
        samples.append({"row": entry["row_idx"], "segment_id": row["segment_id"],
                        "path": str(audio), "seconds": seconds, "sha256": sha256(audio),
                        "reference": row["transcript"]})
    fixture = build_fixture(samples, output)
    if prepare_only:
        report = {'status': 'prepared', 'requests_attempted': 0, 'microphone_used': False,
                  'video_fixture': fixture, 'interpretation': 'Downloaded public human recordings and decoded a real fixture; no Prisma or microphone calls'}
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
        return report
    results = []
    for index, output_format in ((0, "verbatim"), (1, "codemix"), (0, "transliterate")):
        sample = samples[index]
        started = time.monotonic()
        result = {"segment_id": sample["segment_id"], "format": output_format,
                  "reference": sample["reference"], "input_kind": "public human Hindi-English code-switched lecture"}
        try:
            actual = transcribe_audio(sample["path"], output_format=output_format)
            intent, _ = parse_command(actual["text"], activated=False)
            result.update(request_ok=True, actual=actual, elapsed_seconds=round(time.monotonic()-started, 3),
                          ambient_intent=intent, no_ambient_action=intent == "unknown")
            if output_format != "transliterate":
                result["reference_comparison"] = word_error_rate(sample["reference"], actual["text"])
            else:
                result["reference_comparison"] = {"wer": None, "reason": "Published reference is mixed script; no invented Roman reference"}
            result["contains_latin"] = bool(re.search("[A-Za-z]", actual["text"]))
            result["contains_devanagari"] = bool(re.search("[\u0900-\u097F]", actual["text"]))
            result["source_unchanged"] = sha256(Path(sample["path"])) == sample["sha256"]
        except Exception as exc:
            message = safe_error(exc)
            result.update(request_ok=False, error=message, elapsed_seconds=round(time.monotonic()-started, 3))
        results.append(result)
    report = {"status": "completed_with_measurements", "requests_attempted": len(results),
              "source": {"dataset": DATASET, "mirror": MIRROR, "upstream": UPSTREAM,
                         "upstream_license": "CC BY-SA 4.0", "mirror_license_label": "CC BY 4.0",
                         "license_note": "Original OpenSLR attribution/share-alike terms retained; test audio is not bundled in the application release",
                         "provenance": "MUCS technical-lecture speech, recorded by human speakers; not synthesized or read by this test"},
              "samples": samples, "results": results, "video_fixture": fixture, "microphone_used": False,
              "interpretation": "Actual request outcomes and reference errors; not a claim of perfect ASR or tested human command speech"}
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "test_output/practical_speech")
    parser.add_argument('--prepare-only', action='store_true', help='Download and build the public human-speech fixture only; no key or Prisma calls')
    args = parser.parse_args()
    try:
        report = run(args.output, prepare_only=args.prepare_only)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        raise SystemExit(any(not result['request_ok'] or not result.get('source_unchanged')
                             or not result.get('no_ambient_action') for result in report.get('results', [])))
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": safe_error(exc)}), file=sys.stderr)
        raise SystemExit(1)
