"""Durable worker sequence, job and outbound-frame spool."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openjarvis.edge_worker.outbound_frames import persist_normal_outbound
from openjarvis.edge_worker.spool_errors import EdgeSpoolCapacityError
from openjarvis.edge_worker.terminal_outcomes import (
    TERMINAL_STATES,
    migrate_terminal_schema,
    persist_terminal_outcome,
    reserve_terminal_slot,
)

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
    created_at REAL NOT NULL,
    terminal_job_id TEXT
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


@dataclass(frozen=True, slots=True)
class PendingOutboundFrame:
    sequence: int
    wire_json: str


class EdgeWorkerSpool:
    def __init__(
        self,
        path: Path,
        *,
        max_frames: int = 10_000,
        max_bytes: int = 64 * 1024 * 1024,
        terminal_reserve_frames: int = 64,
    ) -> None:
        if max_frames <= 0 or max_bytes <= 0 or terminal_reserve_frames <= 0:
            raise ValueError("Edge spool limits must be positive")
        self.path = path
        self.max_frames = max_frames
        self.max_bytes = max_bytes
        self.terminal_reserve_frames = terminal_reserve_frames
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._transaction() as connection:
            connection.executescript(_SCHEMA)
            migrate_terminal_schema(connection)
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

    def inbound_sequence(self) -> int:
        return self._state_value("inbound_sequence")

    def outbound_sequence(self) -> int:
        return self._state_value("outbound_sequence")

    def reconcile_outbound_sequence(self, minimum: int) -> None:
        if minimum < 0:
            raise ValueError("Outbound sequence minimum cannot be negative")
        with self._transaction() as connection:
            connection.execute(
                "UPDATE worker_state SET value = MAX(value, ?) WHERE key = ?",
                (minimum, "outbound_sequence"),
            )

    def _state_value(self, key: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM worker_state WHERE key = ?", (key,)
            ).fetchone()
        return int(row[0])

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
            persist_normal_outbound(
                connection,
                event_id=event_id,
                sequence=sequence,
                wire_json=wire_json,
                max_frames=self.max_frames,
                max_bytes=self.max_bytes,
            )

    def queue_terminal(
        self,
        *,
        job_id: str,
        state: str,
        event_id: str,
        sequence: int,
        wire_json: str,
    ) -> None:
        """Atomically persist a terminal frame and its local job outcome."""
        with self._transaction() as connection:
            persist_terminal_outcome(
                connection,
                reserve_frames=self.terminal_reserve_frames,
                job_id=job_id,
                state=state,
                event_id=event_id,
                sequence=sequence,
                wire_json=wire_json,
            )

    def acknowledge(self, sequence: int) -> None:
        with self._transaction() as connection:
            connection.execute(
                "DELETE FROM outbound_frames WHERE sequence <= ?", (sequence,)
            )

    def pending_frames(
        self, *, after_sequence: int = 0, limit: int = 100
    ) -> list[PendingOutboundFrame]:
        if after_sequence < 0 or limit <= 0:
            raise ValueError("Invalid Edge spool page")
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT sequence, wire_json FROM outbound_frames "
                "WHERE sequence > ? ORDER BY sequence LIMIT ?",
                (after_sequence, min(limit, 1_000)),
            ).fetchall()
        return [
            PendingOutboundFrame(int(row["sequence"]), str(row["wire_json"]))
            for row in rows
        ]

    def discard_legacy_registration_frames(self) -> int:
        """Remove v1.0 registration frames incorrectly persisted as application data."""
        with self._transaction() as connection:
            return connection.execute(
                "DELETE FROM outbound_frames "
                'WHERE wire_json LIKE \'%"type":"edge.register"%\''
            ).rowcount

    def accept_job_with_frame(
        self,
        *,
        job_id: str,
        attempt_id: str,
        tool_id: str,
        payload_hash: str,
        event_id: str,
        sequence: int,
        wire_json: str,
    ) -> bool:
        """Atomically admit a job together with its durable acceptance frame."""
        now = time.time()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM worker_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if existing is not None:
                if (
                    existing["attempt_id"] != attempt_id
                    or existing["tool_id"] != tool_id
                    or existing["payload_hash"] != payload_hash
                ):
                    raise ValueError("Edge job identity mismatch")
            else:
                reserve_terminal_slot(
                    connection, reserve_frames=self.terminal_reserve_frames
                )
            persist_normal_outbound(
                connection,
                event_id=event_id,
                sequence=sequence,
                wire_json=wire_json,
                max_frames=self.max_frames,
                max_bytes=self.max_bytes,
            )
            if existing is not None:
                return False
            connection.execute(
                "INSERT INTO worker_jobs(job_id, attempt_id, tool_id, payload_hash, "
                "state, accepted_at, updated_at) VALUES (?, ?, ?, ?, 'ACCEPTED', ?, ?)",
                (job_id, attempt_id, tool_id, payload_hash, now, now),
            )
            return True

    def transition(self, job_id: str, state: str) -> None:
        if state in TERMINAL_STATES:
            raise ValueError("Terminal Edge transitions must use queue_terminal")
        with self._transaction() as connection:
            changed = connection.execute(
                "UPDATE worker_jobs SET state = ?, updated_at = ? WHERE job_id = ?",
                (state, time.time(), job_id),
            ).rowcount
            if changed != 1:
                raise ValueError("Edge job transition references an unknown job")

    def job_state(self, job_id: str) -> str | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT state FROM worker_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return None if row is None else str(row["state"])

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
                "SELECT job_id, attempt_id, tool_id FROM worker_jobs "
                "WHERE terminal_event_id IS NULL AND (state IN "
                "('ACCEPTED', 'RUNNING', 'WAITING_APPROVAL', 'RECOVERY_PENDING') "
                "OR state = 'UNKNOWN') ORDER BY accepted_at"
            ).fetchall()
            connection.execute(
                "UPDATE worker_jobs SET state = 'RECOVERY_PENDING', updated_at = ? "
                "WHERE terminal_event_id IS NULL AND state IN "
                "('ACCEPTED', 'RUNNING', 'WAITING_APPROVAL', 'UNKNOWN')",
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


__all__ = [
    "EdgeSpoolCapacityError",
    "EdgeWorkerSpool",
    "PendingOutboundFrame",
]
