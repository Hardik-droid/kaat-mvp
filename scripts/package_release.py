"""Build a source-only release; never bundle credentials, environments, or recordings."""
from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {".env.example", ".gitignore", "README.md", "COMPETITORS.md",
              "THIRD_PARTY.md", "LICENSE", "setup.ps1", "run.ps1", "run_kaat.bat"}
DIRECTORY_SUFFIXES = {"docs": {".md", ".png", ".svg"},
                      "tests": {".py"}, "scripts": {".py", ".ps1", ".md"}, "tools": {".py"},
                      "delivery": {".md"}}


def source_files(root: Path = ROOT) -> list[Path]:
    """Allow known source formats and reject symlinks and hidden/generated folders."""
    root = root.resolve()
    candidates = set(root.glob("*.py")) | set(root.glob("requirements*.txt"))
    candidates.update(root / name for name in ROOT_FILES)
    for directory, suffixes in DIRECTORY_SUFFIXES.items():
        for path in (root / directory).rglob("*"):
            relative = path.relative_to(root / directory)
            if path.suffix in suffixes and not any(part.startswith(".") or part == "__pycache__" for part in relative.parts):
                candidates.add(path)
    return sorted((path for path in candidates if path.is_file() and not path.is_symlink()
                   and path.resolve().is_relative_to(root)), key=lambda path: path.relative_to(root).as_posix())


def build_release(root: Path = ROOT) -> Path:
    root = root.resolve()
    files = source_files(root)
    names = {path.relative_to(root).as_posix() for path in files}
    required = {"app.py", "controller.py", "mcp_server.py", "requirements.txt", "requirements-dev.txt",
                ".env.example", "README.md", "setup.ps1", "run.ps1", "run_kaat.bat", "doctor.py",
                "intent_parser.py", "tools/__init__.py", "tools/windows_apps.py", "scripts/windows_probe.ps1"}
    if missing := required - names:
        raise RuntimeError("Required release files missing: " + ", ".join(sorted(missing)))
    if ".env" in names or any(name.endswith((".sqlite3", ".db", ".mp4", ".wav")) for name in names):
        raise RuntimeError("Private/generated files must never enter a source release")
    destination = root / "dist" / "KAAT-MVP-source.zip"
    destination.parent.mkdir(exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=".kaat_release_", suffix=".zip", dir=destination.parent)
    os.close(descriptor)
    staged = Path(temporary)
    try:
        with ZipFile(staged, "w", compression=ZIP_DEFLATED) as archive:
            for source in files:
                archive.write(source, "KAAT-MVP/" + source.relative_to(root).as_posix())
        with ZipFile(staged) as archive:
            if archive.testzip() is not None or set(archive.namelist()) != {"KAAT-MVP/" + name for name in names}:
                raise RuntimeError("Release ZIP verification failed")
        staged.replace(destination)
    finally:
        staged.unlink(missing_ok=True)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    print(f"Built {destination} ({len(files)} source files, {destination.stat().st_size:,} bytes)")
    print(f"SHA256 {digest}")
    return destination


if __name__ == "__main__":
    build_release()
