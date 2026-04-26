"""
SQLite-backed session history store.

Stores completed JARVIS command entries so history survives restarts.
Database lives at data/session_history.db (gitignored).

Schema
------
  history(id, time, you, jarvis, jTime, intent, conf, status, created_at)

Public API
----------
  store = HistoryStore()        # open / create DB
  store.save_entry(entry)       # insert one completed entry
  store.load_last_n(100)        # newest-last list of dicts
  store.clear()                 # wipe all rows
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

_DB_PATH = Path(__file__).parent.parent / "data" / "session_history.db"

_CREATE_SQL = """
CREATE TABLE IF NOT EXISTS history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    time       TEXT    NOT NULL DEFAULT '',
    you        TEXT    NOT NULL DEFAULT '',
    jarvis     TEXT    NOT NULL DEFAULT '',
    jTime      TEXT    NOT NULL DEFAULT '',
    intent     TEXT    NOT NULL DEFAULT '',
    conf       REAL    NOT NULL DEFAULT 0.0,
    status     TEXT    NOT NULL DEFAULT 'success',
    created_at INTEGER NOT NULL
)
"""

_INSERT_SQL = """
INSERT INTO history (time, you, jarvis, jTime, intent, conf, status, created_at)
VALUES (:time, :you, :jarvis, :jTime, :intent, :conf, :status, :created_at)
"""

_LOAD_SQL = """
SELECT time, you, jarvis, jTime, intent, conf, status
FROM history
ORDER BY id DESC
LIMIT ?
"""

_CLEAR_SQL = "DELETE FROM history"


class HistoryStore:
    """Thread-safe SQLite wrapper for JARVIS command history."""

    def __init__(self, db_path: Path = _DB_PATH) -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn: sqlite3.Connection | None = None
        self._open()

    def _open(self) -> None:
        try:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(
                str(self._db_path),
                check_same_thread=False,
                timeout=5,
            )
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute(_CREATE_SQL)
            self._conn.commit()
        except Exception as exc:
            print(f"[history_store] Failed to open DB: {exc}")
            self._conn = None

    def save_entry(self, entry: dict[str, Any]) -> None:
        """Persist one completed entry. Skips pending or empty entries."""
        if not entry or entry.get("status") == "pending":
            return
        you = (entry.get("you") or "").strip()
        if not you:
            return
        row = {
            "time":       str(entry.get("time", "")),
            "you":        you,
            "jarvis":     str(entry.get("jarvis", "")),
            "jTime":      str(entry.get("jTime", "")),
            "intent":     str(entry.get("intent", "")),
            "conf":       float(entry.get("conf", entry.get("confidence", 0.0))),
            "status":     str(entry.get("status", "success")),
            "created_at": int(time.time()),
        }
        if self._conn is None:
            return
        with self._lock:
            try:
                self._conn.execute(_INSERT_SQL, row)
                self._conn.commit()
            except Exception as exc:
                print(f"[history_store] save_entry error: {exc}")

    def load_last_n(self, n: int = 100) -> list[dict[str, Any]]:
        """Return the last n entries in chronological order (oldest first)."""
        if self._conn is None:
            return []
        with self._lock:
            try:
                cur = self._conn.execute(_LOAD_SQL, (n,))
                cols = [d[0] for d in cur.description]
                rows = cur.fetchall()
                # Reverse: DB gives newest-first (ORDER BY id DESC); we want oldest-first
                return [dict(zip(cols, row)) for row in reversed(rows)]
            except Exception as exc:
                print(f"[history_store] load_last_n error: {exc}")
                return []

    def clear(self) -> None:
        """Delete all history rows."""
        if self._conn is None:
            return
        with self._lock:
            try:
                self._conn.execute(_CLEAR_SQL)
                self._conn.commit()
            except Exception as exc:
                print(f"[history_store] clear error: {exc}")

    def close(self) -> None:
        if self._conn:
            with self._lock:
                try:
                    self._conn.close()
                except Exception:
                    pass
                self._conn = None


# Module-level singleton — imported by main.py
history_store = HistoryStore()
