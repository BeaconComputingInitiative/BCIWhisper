# BEACON COMPUTING INITIATIVE
# BCIWhisper Script 58.3 | Engineering Build 2026.10.23-r6.35.3
# Developer Seal: CJB-DEV-2026

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from time import time

from bciwhisper.config.paths import TELEMETRY_DB


class TelemetryDatabase:
    def __init__(self, path: Path | str = TELEMETRY_DB) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                unix_time REAL NOT NULL,
                name TEXT NOT NULL,
                payload_json TEXT NOT NULL
            )
            """
        )
        self._conn.commit()

    def log(self, name: str, payload: dict) -> None:
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            self._conn.execute(
                "INSERT INTO events(unix_time, name, payload_json) VALUES (?, ?, ?)",
                (time(), str(name), encoded),
            )
            self._conn.commit()

    def recent(self, limit: int = 100) -> list[dict]:
        limit = max(1, min(int(limit), 1000))
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, unix_time, name, payload_json FROM events ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            try:
                payload = json.loads(row[3])
            except Exception:
                payload = {"raw": row[3]}
            out.append({"id": row[0], "unix_time": row[1], "name": row[2], "payload": payload})
        return out

    def close(self) -> None:
        with self._lock:
            self._conn.close()
