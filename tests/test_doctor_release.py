"""Real local diagnostic/packaging checks; no provider or hardware success doubles."""
import json
import os
from pathlib import Path
import subprocess
import sys

from doctor import _safe_error
from scripts.package_release import source_files


def test_startup_missing_key_does_not_block_typed_commands(tmp_path):
    root = Path(__file__).resolve().parents[1]
    env = {**os.environ, "GNANI_API_KEY": "", "KAAT_DATA_DIR": str(tmp_path / "memory")}
    result = subprocess.run([sys.executable, str(root / "doctor.py"), "--startup", "--json"],
                            cwd=root, env=env, capture_output=True, text=True, timeout=30)
    rows = {row["check"]: row for row in json.loads(result.stdout)}
    assert rows["Gnani API key"]["status"] == "FAIL"
    assert rows["Gnani authenticated transcription"]["status"] == "NOT TESTED"
    assert rows["Microphone availability"]["status"] == "NOT TESTED"
    critical_failures = any(row["critical"] and row["status"] == "FAIL" for row in rows.values())
    assert result.returncode == (1 if critical_failures else 0)


def test_diagnostic_errors_redact_key(monkeypatch):
    monkeypatch.setenv("GNANI_API_KEY", "unit-test-secret-value")
    assert _safe_error(ValueError("rejected unit-test-secret-value")) == "rejected [REDACTED]"


def test_release_includes_launchers_without_private_files(tmp_path):
    for name in ("doctor.py", "intent_parser.py", "run_kaat.bat", "tools/__init__.py", "tools/windows_apps.py",
                 ".env", "test_output/private.wav", "test_output/private.json", "tools/__pycache__/private.pyc"):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("fixture", encoding="utf-8")
    names = {path.relative_to(tmp_path).as_posix() for path in source_files(tmp_path)}
    assert names == {"doctor.py", "intent_parser.py", "run_kaat.bat", "tools/__init__.py", "tools/windows_apps.py"}
