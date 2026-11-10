"""Truthful local diagnostics. Inventory is not a capture or recognition test."""
from __future__ import annotations

import argparse
import importlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import platform
import socket
import ssl
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
PACKAGES = {
    "python-dotenv": "dotenv", "gnani-vachana": "gnani.stt",
    "sounddevice": "sounddevice", "webrtcvad-wheels": "webrtcvad", "mcp": "mcp",
}


def _safe_error(exc):
    # Do not print raw HTTP response bodies or credentials from any dependency.
    message = str(exc)
    key = os.getenv("GNANI_API_KEY", "").strip()
    return (message.replace(key, "[REDACTED]") if key else message)[:600]


def _probe(code, timeout=20):
    """Keep native driver discovery bounded even when a driver stalls."""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                            capture_output=True, text=True, encoding="utf-8",
                            errors="replace", timeout=timeout,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if result.returncode:
        raise RuntimeError(result.stderr.strip().splitlines()[-1] if result.stderr.strip()
                           else "Diagnostic subprocess failed")
    return json.loads(result.stdout)


def diagnose(*, startup=False, audio=None, output_dir=None):
    results = []

    def report(name, status, detail, critical=False):
        results.append({"check": name, "status": status, "detail": detail, "critical": critical})

    def check(name, function, critical=False):
        try:
            report(name, "PASS", function(), critical)
        except Exception as exc:
            report(name, "FAIL", _safe_error(exc), critical)

    report("Python", "PASS" if sys.version_info >= (3, 10) else "FAIL",
           f"{platform.python_version()} ({sys.executable}); requires 3.10+", True)
    report("Windows", "PASS" if os.name == "nt" else "FAIL", platform.platform(), True)
    for package, module in PACKAGES.items():
        def dependency(package=package, module=module):
            importlib.import_module(module)
            return f"{package} {version(package)} imports successfully"
        check(package, dependency, True)

    def tkinter_check():
        import tkinter
        return "Tcl/Tk " + tkinter.Tcl().eval("info patchlevel")
    check("Tkinter", tkinter_check, True)

    # Load only the project's private environment file; never print its values.
    try:
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env")
    except ImportError:
        pass  # Already reported as a required dependency failure above.

    for name in ("ffmpeg", "ffprobe"):
        def binary(name=name):
            from engine import _binary
            executable = _binary(name)
            result = subprocess.run([executable, "-version"], capture_output=True, text=True,
                                    encoding="utf-8", errors="replace", timeout=10,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if result.returncode:
                raise RuntimeError(f"{name} failed to run; repair FFmpeg or rerun setup.ps1 -DownloadFFmpeg")
            return result.stdout.splitlines()[0] + " | " + executable
        check(name, binary, True)

    def writable():
        target = Path(output_dir or Path.cwd()).expanduser().resolve(strict=True)
        if not target.is_dir():
            raise ValueError("Output directory is not a directory")
        with tempfile.TemporaryFile(dir=target) as handle:
            handle.write(b"KAAT write/read check")
            handle.flush()
            handle.seek(0)
            if handle.read() != b"KAAT write/read check":
                raise RuntimeError("Output directory write/read verification failed")
        return str(target) + "; write/read passed (other export folders need their own check)"
    check("Writable output directory", writable, True)

    def local_memory():
        from memory import data_directory
        with tempfile.TemporaryFile(dir=data_directory()) as handle:
            handle.write(b"KAAT")
            handle.flush()
        return str(data_directory()) + "; writable"
    check("Local data directory", local_memory, True)

    key_present = bool(os.getenv("GNANI_API_KEY", "").strip())
    report("Gnani API key", "PASS" if key_present else "FAIL",
           "Present; value hidden. Presence does not prove validity." if key_present else
           "GNANI NOT CONNECTED - CHECK API KEY. Set GNANI_API_KEY privately in .env; typed commands remain available.")

    if startup:
        for name in ("Microphone availability", "Camera availability", "Gnani TLS connectivity", "Gnani authenticated transcription"):
            report(name, "NOT TESTED", "Skipped by --startup; run doctor.py for device/network diagnostics.")
        return results

    def microphone():
        devices = _probe("import json; from voice import list_microphones; print(json.dumps(list_microphones()))")
        if not devices:
            raise RuntimeError("No input device found. Connect/enable a microphone in Windows Sound settings.")
        from voice import microphone_permission_error
        if reason := microphone_permission_error():
            raise PermissionError(reason)
        return "; ".join(devices) + "; inventory only, no audio captured"
    check("Microphone availability", microphone)
    report("Microphone capture", "NOT TESTED", "Use KAAT's microphone button and speak after Listening. This checker never opens the microphone.")

    def camera():
        status = _probe("import json; from system_tools import device_status; print(json.dumps(device_status()))", 22)
        if status.get("enumeration_error"):
            raise RuntimeError(status["enumeration_error"])
        devices = [row["name"] for row in status["devices"] if row["kind"] == "video"]
        if not devices:
            raise RuntimeError("No DirectShow camera found. Connect/enable a camera in Windows settings.")
        if status["camera"]["status"] == "blocked":
            raise PermissionError("Windows camera access is blocked; enable the Camera app in Windows privacy settings.")
        return "; ".join(devices) + "; Windows Camera " + ("registered" if status["camera_app_available"] else "not registered") + "; inventory only"
    check("Camera availability", camera)
    report("Camera capture", "NOT TESTED", "No camera was opened or recorded by this checker.")

    if key_present:
        def connectivity():
            from gnani.stt.client import DEFAULT_BASE_URL
            host = urlsplit(DEFAULT_BASE_URL).hostname
            with socket.create_connection((host, 443), timeout=8) as connection:
                with ssl.create_default_context().wrap_socket(connection, server_hostname=host) as tls:
                    return f"{host}:443 {tls.version()} handshake passed; does not validate the API key"
        check("Gnani TLS connectivity", connectivity)
    else:
        report("Gnani TLS connectivity", "NOT TESTED", "No configured key; network probe omitted.")

    if audio is not None and key_present:
        def transcription():
            from voice import transcribe_audio
            result = transcribe_audio(audio, output_format="transliterate")
            if not result["text"]:
                raise RuntimeError("Actual Prisma response contained no speech; use a short human speech WAV.")
            return (f"Actual {result['model']} response contained {len(result['text'])} text characters; "
                    f"request_id={result.get('request_id') or 'not supplied'}. Text is not logged; accuracy was not scored.")
        check("Gnani authenticated transcription", transcription)
    else:
        report("Gnani authenticated transcription", "NOT TESTED",
               "Provide --audio PATH to an explicitly selected human speech clip (up to 30 seconds) and a key. No synthetic transcript or audio is sent.")
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--startup", action="store_true", help="Check local startup dependencies only; no device or network probes")
    parser.add_argument("--audio", type=Path, help="Send this explicitly selected <=30-second speech clip to real Gnani (may consume API credit)")
    parser.add_argument("--output-dir", type=Path, help="Existing folder to check for write access (default: current folder)")
    parser.add_argument("--json", action="store_true", help="Print structured results")
    args = parser.parse_args()
    if args.startup and args.audio:
        parser.error("--startup cannot be combined with --audio")
    results = diagnose(startup=args.startup, audio=args.audio, output_dir=args.output_dir)
    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=True))
    else:
        for row in results:
            print(f"{row['status']:10} {row['check']}: {row['detail']}")
        print("PASS means only the named check passed. NOT TESTED is never a pass.")
    failed = any(row["status"] == "FAIL" and (not args.startup or row["critical"]) for row in results)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
