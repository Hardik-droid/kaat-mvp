"""Reproducible local editing proof using generated tones, never simulated speech."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from controller import AgentController
from engine import _binary, duration, source_hash


def run_demo(output: Path) -> dict:
    output = output.expanduser().resolve()
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError("Choose an empty or new output directory; the demo never replaces existing files.")
    output.mkdir(parents=True, exist_ok=True)
    source, edited = output / "source_synthetic.mp4", output / "cleaned_synthetic.mp4"
    # 1 second tone, 2.5 seconds silence, 1 second tone. This is not a speech demo.
    process = subprocess.run([
        _binary("ffmpeg"), "-hide_banner", "-loglevel", "error", "-nostdin",
        "-f", "lavfi", "-i", "testsrc2=size=480x270:rate=25:duration=4.5",
        "-f", "lavfi", "-i",
        r"aevalsrc=if(lt(t\,1)\,0.12*sin(2*PI*440*t)\,if(gt(t\,3.5)\,0.12*sin(2*PI*440*t)\,0)):d=4.5:s=16000",
        "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-c:a", "aac", str(source),
    ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    if process.returncode:
        raise RuntimeError("Synthetic sample generation failed: " + process.stderr[-1500:])
    original_hash = source_hash(source)
    controller = AgentController(memory_path=output / "demo.sqlite3")
    steps = []

    def call(tool, **arguments):
        response = controller.call(tool, **arguments)
        if not response["ok"]:
            raise RuntimeError(f"{tool}: {response['error']['message']}")
        steps.append({"tool": tool, "ok": True})
        return response["data"]

    try:
        call("video.inspect", source=str(source))
        detected = call("video.detect_pauses")
        cuts = detected["cuts"]
        if not cuts or any(c["status"] != "suggested" for c in cuts):
            raise RuntimeError("Expected actual silence proposals requiring approval.")
        before_approval = call("session.state")
        if abs(before_approval["edited_duration"] - before_approval["original_duration"]) > .01:
            raise RuntimeError("Unapproved suggestions incorrectly changed edited duration.")
        last_approved = None
        for cut in cuts:
            call("video.approve_cut", cut_id=cut["id"])
            last_approved = cut["id"]
        approved = call("session.state")
        call("video.undo")
        undone = call("session.state")
        if not any(c["id"] == last_approved and c["status"] == "suggested" for c in undone["cuts"]):
            raise RuntimeError("Undo did not restore the last approved suggestion.")
        call("video.approve_cut", cut_id=last_approved)
        exported = call("video.export", output=str(edited))
        after_hash = source_hash(source)
        actual_duration = duration(edited)
        if original_hash != after_hash:
            raise RuntimeError("Source SHA256 changed.")
        if actual_duration >= before_approval["original_duration"] - 1.5:
            raise RuntimeError("The generated silence was not removed from the actual MP4.")
        plan = json.loads(Path(exported["edl"]).read_text(encoding="utf-8"))
        if plan["source_sha256"] != original_hash:
            raise RuntimeError("EDL source fingerprint does not match the original.")
        report = {
            "demo_kind": "generated video with tones and silence; no human speech",
            "status": "passed", "gnani_called": False, "microphone_used": False,
            "source": str(source), "edited": str(edited), "edl": exported["edl"],
            "source_sha256_before": original_hash, "source_sha256_after": after_hash,
            "source_unchanged": original_hash == after_hash,
            "detected_cuts": cuts,
            "original_duration_seconds": before_approval["original_duration"],
            "duration_before_approval_seconds": before_approval["edited_duration"],
            "planned_edited_duration_seconds": approved["edited_duration"],
            "duration_after_undo_seconds": undone["edited_duration"],
            "actual_export_duration_seconds": actual_duration,
            "undo_verified": True, "tool_steps": steps,
            "unverified_by_this_demo": ["Gnani authentication and real Hinglish transcription",
                                        "microphone hardware", "camera recording", "desktop visual layout"],
        }
        with (output / "report.json").open("x", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        return report
    finally:
        controller.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "demo_output",
                        help="Empty or new output directory (default: demo_output).")
    arguments = parser.parse_args()
    try:
        report = run_demo(arguments.output)
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
