"""SQLite preferences, session and bounded task history; no microphone archive."""
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path


def data_directory():
    path = Path(os.getenv("KAAT_DATA_DIR", str(Path.home() / ".kaat"))).expanduser()
    path.mkdir(parents=True, exist_ok=True)
    return path


class Memory:
    def __init__(self, path=None):
        self.path = Path(path) if path else data_directory() / "kaat.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS session(id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY, at TEXT DEFAULT CURRENT_TIMESTAMP,
                    tool TEXT NOT NULL, ok INTEGER NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS opened_windows(hwnd INTEGER NOT NULL, nonce INTEGER NOT NULL,
                    value TEXT NOT NULL, PRIMARY KEY(hwnd, nonce));
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            # sqlite3.Connection.__exit__ commits/rolls back but does not close.
            db.close()

    @staticmethod
    def validate(key, value):
        if key == "pause_threshold":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not .2 <= value <= 20:
                raise ValueError("Pause threshold must be 0.2–20 seconds")
        elif key in {"burn_subtitles", "preserve_original"}:
            if not isinstance(value, bool):
                raise ValueError(key + " must be true or false")
            if key == 'preserve_original' and not value:
                raise ValueError('Original preservation cannot be disabled')
        elif key == 'capture_seconds':
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not .5 <= value <= 25:
                raise ValueError('Capture duration must be 0.5–25 seconds')
        elif key == 'microphone':
            if not isinstance(value, str) or len(value) > 300 or any(ord(c) < 32 for c in value):
                raise ValueError('Choose a valid local microphone name')
        else:
            raise ValueError("Supported preferences: pause_threshold, burn_subtitles, preserve_original, capture_seconds, microphone")

    def save(self, key, value, approved=False):
        if approved is not True:
            raise ValueError("Saving preferences requires an explicit user request or approval")
        self.validate(key, value)
        with self.connect() as db:
            db.execute("INSERT INTO preferences VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                       (key, json.dumps(value)))
        return self.preferences()

    def preferences(self):
        with self.connect() as db:
            return {k: json.loads(v) for k, v in db.execute("SELECT key,value FROM preferences ORDER BY key")}

    def delete(self, key):
        if key not in {"pause_threshold", "burn_subtitles", "microphone", "preserve_original", "capture_seconds"}:
            raise ValueError("Unsupported preference")
        with self.connect() as db:
            db.execute("DELETE FROM preferences WHERE key=?", (key,))
        return self.preferences()

    def save_session(self, value):
        with self.connect() as db:
            db.execute("INSERT INTO session VALUES(1,?) ON CONFLICT(id) DO UPDATE SET value=excluded.value", (json.dumps(value),))

    def save_opened_windows(self, records):
        with self.connect() as db:
            for record in records:
                db.execute('INSERT OR REPLACE INTO opened_windows VALUES(?,?,?)',
                           (record['hwnd'], record['nonce'], json.dumps(record)))

    def opened_windows(self):
        with self.connect() as db:
            return [json.loads(row[0]) for row in db.execute('SELECT value FROM opened_windows ORDER BY rowid')]

    def remove_opened_windows(self, records):
        with self.connect() as db:
            db.executemany('DELETE FROM opened_windows WHERE hwnd=? AND nonce=?',
                           [(record['hwnd'], record['nonce']) for record in records])

    def session(self):
        with self.connect() as db:
            row = db.execute("SELECT value FROM session WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}

    def record(self, tool, ok, detail):
        with self.connect() as db:
            db.execute("INSERT INTO history(tool,ok,detail) VALUES(?,?,?)", (tool, int(ok), str(detail)[:1500]))
            db.execute("DELETE FROM history WHERE id NOT IN (SELECT id FROM history ORDER BY id DESC LIMIT 500)")

    def history(self, limit=50):
        with self.connect() as db:
            return [dict(zip(("at", "tool", "ok", "detail"), row)) for row in db.execute(
                "SELECT at,tool,ok,detail FROM history ORDER BY id DESC LIMIT ?", (min(max(int(limit), 1), 500),))]
