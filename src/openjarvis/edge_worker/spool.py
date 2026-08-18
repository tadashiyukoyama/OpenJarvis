"""Durable worker sequence, job and outbound-frame spool."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS worker_state (
    key TEXT PRIMARY KEY,
    value INTEGER NOT NULL
);
INSERT OR IGNORE INTO worker_state(key, value) VALUES ('outbound_sequence', 0);
INSERT OR IGNORE INTO worker_state(key, value) VALUES ('inbound_sequence', 0);

CREATE TABLE IF NOT EXISTS inbound_events (
    event_id TEXT PRIMARY KEY,
    sequence INTEGER NOT NULL,
    received_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS outbound_frames (
    event_id TEXT PRIMARY KEY,
    sequence INTEGER NOT NULL UNIQUE,
    wire_json TEXT NOT NULL,
    created_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS worker_jobs (
    job_id TEXT PRIMARY KEY,
    attempt_id TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    accepted_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    terminal_event_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_worker_jobs_state
ON worker_jobs(state, updated_at);
"""


class EdgeWorkerSpool:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._transaction() as connection:
            connection.executescript(_SCHEMA)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if integrity != "ok":
                raise RuntimeError("Edge worker spool integrity check failed")

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=10000")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self._connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except BaseException:
                connection.rollback()
                raise
            finally:
                connection.close()

    def next_outbound_sequence(self) -> int:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE worker_state SET value = value + 1 WHERE key = ?",
                ("outbound_sequence",),
            )
            return int(
                connection.execute(
                    "SELECT value FROM worker_state WHERE key = ?",
                    ("outbound_sequence",),
                ).fetchone()[0]
            )

    def record_inbound(self, event_id: str, sequence: int) -> bool:
        with self._transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM inbound_events WHERE event_id = ?", (event_id,)
            ).fetchone():
                return False
            current = int(
                connection.execute(
                    "SELECT value FROM worker_state WHERE key = ?",
                    ("inbound_sequence",),
                ).fetchone()[0]
            )
            if sequence <= current:
                raise ValueError("Core frame sequence moved backwards")
            connection.execute(
                "INSERT INTO inbound_events(event_id, sequence, received_at) "
                "VALUES (?, ?, ?)",
                (event_id, sequence, time.time()),
            )
            connection.execute(
                "UPDATE worker_state SET value = ? WHERE key = ?",
                (sequence, "inbound_sequence"),
            )
            return True

    def queue_outbound(self, event_id: str, sequence: int, wire_json: str) -> None:
        with self._transaction() as connection:
            connection.execute(
                "INSERT OR IGNORE INTO outbound_frames"
                "(event_id, sequence, wire_json, created_at) VALUES (?, ?, ?, ?)",
                (event_id, sequence, wire_json, time.time()),
            )

    def acknowledge(self, sequence: int) -> None:
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM outbound_frames WHERE sequence <= ?", (sequence,)
            )

    def pending_frames(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT wire_json FROM outbound_frames ORDER BY sequence"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def accept_job(
        self, *, job_id: str, attempt_id: str, tool_id: str, payload_hash: str
    ) -> bool:
        now = time.time()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM worker_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["attempt_id"] != attempt_id
                    or existing["payload_hash"] != payload_hash
                ):
                    raise ValueError("Edge job identity mismatch")
                return False
            connection.execute(
                "INSERT INTO worker_jobs(job_id, attempt_id, tool_id, payload_hash, "
                "state, accepted_at, updated_at) VALUES (?, ?, ?, ?, 'ACCEPTED', ?, ?)",
                (job_id, attempt_id, tool_id, payload_hash, now, now),
            )
            return True

    def transition(self, job_id: str, state: str, terminal_event_id: str = "") -> None:
        with self._transaction() as connection:
            connection.execute(
                "UPDATE worker_jobs SET state = ?, updated_at = ?, "
                "terminal_event_id = COALESCE(NULLIF(?, ''), terminal_event_id) "
                "WHERE job_id = ?",
                (state, time.time(), terminal_event_id, job_id),
            )

    def active_job_ids(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id FROM worker_jobs WHERE state IN "
                "('ACCEPTED', 'RUNNING', 'WAITING_APPROVAL') ORDER BY accepted_at"
            ).fetchall()
        return [str(row[0]) for row in rows]

    def recover_interrupted(self) -> list[dict[str, Any]]:
        with self._transaction() as connection:
            rows = connection.execute(
                "SELECT job_id, attempt_id, tool_id FROM worker_jobs WHERE state IN "
                "('ACCEPTED', 'RUNNING', 'WAITING_APPROVAL') ORDER BY accepted_at"
            ).fetchall()
            connection.execute(
                "UPDATE worker_jobs SET state = 'UNKNOWN', updated_at = ? "
                "WHERE state IN ('ACCEPTED', 'RUNNING', 'WAITING_APPROVAL')",
                (time.time(),),
            )
            return [dict(row) for row in rows]

    def prune(self, *, before: float) -> None:
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM inbound_events WHERE received_at < ?", (before,)
            )
            connection.execute(
                "DELETE FROM worker_jobs WHERE updated_at < ? AND state IN "
                "('SUCCEEDED', 'FAILED', 'CANCELLED', 'UNKNOWN')",
                (before,),
            )


__all__ = ["EdgeWorkerSpool"]
