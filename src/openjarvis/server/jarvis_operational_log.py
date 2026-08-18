"""Durable, sanitized operational memory for the local Jarvis voice layer."""

from __future__ import annotations

import re
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

_ALLOWED_EVENT_TYPES = {
    "system",
    "user",
    "jarvis",
    "codex",
    "approval",
    "error",
    "tool",
    "dispatch",
    "session",
}
# Keep the full bounded Codex report available to the Jarvis read-only tools.
# The frontend still compacts older events before sending them to Gemini.
_MAX_EVENT_TEXT = 8_000
_MAX_EVENTS_PER_THREAD = 500

_SENSITIVE_PATTERNS = (
    re.compile(r"\bAIza[0-9A-Za-z_-]{24,}\b"),
    re.compile(r"\bsk-(?:proj-)?[0-9A-Za-z_-]{20,}\b"),
    re.compile(r"\b[A-Z]{1,5}\.[0-9A-Za-z_-]{24,}\b"),
    re.compile(
        r"\b(api[_ -]?key|token|secret|password|senha)(\s*[:=]\s*)([^\s,;]+)",
        re.IGNORECASE,
    ),
    re.compile(r"\bBearer\s+[0-9A-Za-z._~-]{20,}\b", re.IGNORECASE),
)


def sanitize_operational_text(text: str) -> str:
    """Remove credential-shaped values before an event reaches durable storage."""

    sanitized = str(text)
    for index, pattern in enumerate(_SENSITIVE_PATTERNS):
        if index == 3:
            sanitized = pattern.sub(r"\1\2[credencial omitida]", sanitized)
        elif index == 4:
            sanitized = pattern.sub("Bearer [credencial omitida]", sanitized)
        else:
            sanitized = pattern.sub("[credencial omitida]", sanitized)
    return " ".join(sanitized.split())[:_MAX_EVENT_TEXT]


@dataclass(frozen=True)
class JarvisOperationalEvent:
    event_id: str
    thread_id: str
    project_cwd: str
    event_type: str
    text: str
    occurred_at: int

    def to_dict(self) -> dict:
        return asdict(self)


class JarvisOperationalLogStore:
    """Small SQLite ledger keyed by the selected Codex thread."""

    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = database_path
        if database_path is not None:
            database_path.parent.mkdir(parents=True, exist_ok=True)
            target = str(database_path)
        else:
            target = ":memory:"
        self._connection = sqlite3.connect(
            target,
            check_same_thread=False,
            timeout=1.0,
        )
        self._connection.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._connection.execute("PRAGMA busy_timeout=1000")
            self._connection.execute("PRAGMA journal_mode=WAL")
            self._connection.execute("PRAGMA synchronous=NORMAL")
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS jarvis_operational_events (
                    event_id TEXT PRIMARY KEY,
                    thread_id TEXT NOT NULL,
                    project_cwd TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    text TEXT NOT NULL,
                    occurred_at INTEGER NOT NULL
                )
                """
            )
            self._connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_jarvis_events_thread_time
                ON jarvis_operational_events(thread_id, occurred_at)
                """
            )
            self._connection.commit()

    def append(
        self,
        *,
        thread_id: str,
        project_cwd: str,
        event_type: str,
        text: str,
        event_id: str | None = None,
        occurred_at: int | None = None,
    ) -> JarvisOperationalEvent:
        normalized_type = event_type.strip().lower()
        if normalized_type not in _ALLOWED_EVENT_TYPES:
            raise ValueError("unsupported Jarvis operational event type")
        normalized_thread = thread_id.strip()
        if not normalized_thread:
            raise ValueError("thread_id is required")
        normalized_text = sanitize_operational_text(text)
        if not normalized_text:
            raise ValueError("event text is required")

        event = JarvisOperationalEvent(
            event_id=(event_id or str(uuid.uuid4())).strip()[:160],
            thread_id=normalized_thread[:256],
            project_cwd=sanitize_operational_text(project_cwd)[:1_024],
            event_type=normalized_type,
            text=normalized_text,
            occurred_at=occurred_at
            if occurred_at is not None
            else int(time.time() * 1000),
        )
        with self._lock:
            self._connection.execute(
                """
                INSERT OR IGNORE INTO jarvis_operational_events (
                    event_id, thread_id, project_cwd, event_type, text, occurred_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.thread_id,
                    event.project_cwd,
                    event.event_type,
                    event.text,
                    event.occurred_at,
                ),
            )
            self._connection.execute(
                """
                DELETE FROM jarvis_operational_events
                WHERE thread_id = ? AND event_id NOT IN (
                    SELECT event_id FROM jarvis_operational_events
                    WHERE thread_id = ?
                    ORDER BY occurred_at DESC, rowid DESC
                    LIMIT ?
                )
                """,
                (event.thread_id, event.thread_id, _MAX_EVENTS_PER_THREAD),
            )
            self._connection.commit()
            row = self._connection.execute(
                """
                SELECT event_id, thread_id, project_cwd, event_type, text, occurred_at
                FROM jarvis_operational_events WHERE event_id = ?
                """,
                (event.event_id,),
            ).fetchone()
        if row is None:
            raise RuntimeError("failed to persist Jarvis operational event")
        return JarvisOperationalEvent(**dict(row))

    def list(self, thread_id: str, *, limit: int = 50) -> list[JarvisOperationalEvent]:
        bounded_limit = min(100, max(1, int(limit)))
        with self._lock:
            rows = self._connection.execute(
                """
                SELECT event_id, thread_id, project_cwd, event_type, text, occurred_at
                FROM (
                    SELECT rowid AS storage_order, event_id, thread_id, project_cwd,
                           event_type, text, occurred_at
                    FROM jarvis_operational_events
                    WHERE thread_id = ?
                    ORDER BY occurred_at DESC, rowid DESC
                    LIMIT ?
                )
                ORDER BY occurred_at ASC, storage_order ASC
                """,
                (thread_id.strip(), bounded_limit),
            ).fetchall()
        return [
            JarvisOperationalEvent(
                **{k: row[k] for k in row.keys() if k != "storage_order"}
            )
            for row in rows
        ]

    def close(self) -> None:
        with self._lock:
            self._connection.close()


__all__ = [
    "JarvisOperationalEvent",
    "JarvisOperationalLogStore",
    "sanitize_operational_text",
]
