"""Reserved durable storage for terminal Edge job outcomes."""

from __future__ import annotations

import sqlite3
import time

from openjarvis.edge_worker.spool_errors import (
    EdgeSpoolCapacityError,
    EdgeTerminalPayloadError,
)
from openjarvis.server.jarvis_agent.edge.frames import MAX_EDGE_FRAME_BYTES

TERMINAL_STATES = frozenset({"SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN"})


def migrate_terminal_schema(connection: sqlite3.Connection) -> None:
    columns = {
        str(row["name"])
        for row in connection.execute("PRAGMA table_info(outbound_frames)")
    }
    if "terminal_job_id" not in columns:
        connection.execute(
            "ALTER TABLE outbound_frames ADD COLUMN terminal_job_id TEXT"
        )
    connection.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_outbound_terminal_job "
        "ON outbound_frames(terminal_job_id) "
        "WHERE terminal_job_id IS NOT NULL"
    )


def reserve_terminal_slot(
    connection: sqlite3.Connection, *, reserve_frames: int
) -> None:
    """Reject admission unless every accepted job retains a terminal slot."""
    pending_terminals = int(
        connection.execute(
            "SELECT COUNT(*) FROM outbound_frames WHERE terminal_job_id IS NOT NULL"
        ).fetchone()[0]
    )
    reserved_jobs = int(
        connection.execute(
            "SELECT COUNT(*) FROM worker_jobs "
            "WHERE terminal_event_id IS NULL AND state IN "
            "('ACCEPTED', 'RUNNING', 'WAITING_APPROVAL', "
            "'RECOVERY_PENDING', 'UNKNOWN')"
        ).fetchone()[0]
    )
    if pending_terminals + reserved_jobs >= reserve_frames:
        raise EdgeSpoolCapacityError(
            "Edge terminal reserve exhausted; new job was not accepted"
        )


def persist_terminal_outcome(
    connection: sqlite3.Connection,
    *,
    reserve_frames: int,
    job_id: str,
    state: str,
    event_id: str,
    sequence: int,
    wire_json: str,
) -> None:
    """Insert the terminal frame and transition its job in one transaction."""
    if state not in TERMINAL_STATES:
        raise ValueError("Invalid Edge terminal job state")
    wire_bytes = len(wire_json.encode("utf-8"))
    if wire_bytes > MAX_EDGE_FRAME_BYTES:
        raise EdgeTerminalPayloadError(
            "Edge terminal frame exceeds the protocol size limit"
        )

    existing = connection.execute(
        "SELECT sequence, wire_json, terminal_job_id FROM outbound_frames "
        "WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    job = connection.execute(
        "SELECT state, terminal_event_id FROM worker_jobs WHERE job_id = ?",
        (job_id,),
    ).fetchone()
    if job is None:
        raise ValueError("Edge terminal event references an unknown job")
    if existing is not None:
        identity_changed = (
            int(existing["sequence"]) != sequence
            or existing["wire_json"] != wire_json
            or existing["terminal_job_id"] != job_id
            or job["state"] != state
            or job["terminal_event_id"] != event_id
        )
        if identity_changed:
            raise ValueError("Edge terminal event identity mismatch")
        return
    if job["terminal_event_id"] is not None:
        if job["terminal_event_id"] == event_id and job["state"] == state:
            return
        raise ValueError("Edge job already has a terminal outcome")
    if job["state"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
        raise ValueError("Edge job is already terminal")
    if job["state"] == "UNKNOWN" and state != "UNKNOWN":
        raise ValueError("Unknown Edge result cannot move to another state")

    stats = connection.execute(
        "SELECT COUNT(*) AS frame_count, "
        "COALESCE(SUM(LENGTH(CAST(wire_json AS BLOB))), 0) AS byte_count "
        "FROM outbound_frames WHERE terminal_job_id IS NOT NULL"
    ).fetchone()
    reserve_bytes = reserve_frames * MAX_EDGE_FRAME_BYTES
    if (
        int(stats["frame_count"]) >= reserve_frames
        or int(stats["byte_count"]) + wire_bytes > reserve_bytes
    ):
        raise EdgeSpoolCapacityError(
            "Edge terminal reserve exhausted; job outcome was not queued"
        )

    connection.execute(
        "INSERT INTO outbound_frames(event_id, sequence, wire_json, created_at, "
        "terminal_job_id) VALUES (?, ?, ?, ?, ?)",
        (event_id, sequence, wire_json, time.time(), job_id),
    )
    changed = connection.execute(
        "UPDATE worker_jobs SET state = ?, updated_at = ?, terminal_event_id = ? "
        "WHERE job_id = ? AND terminal_event_id IS NULL",
        (state, time.time(), event_id, job_id),
    ).rowcount
    if changed != 1:
        raise ValueError("Edge terminal job transition was not applied")


__all__ = [
    "TERMINAL_STATES",
    "migrate_terminal_schema",
    "persist_terminal_outcome",
    "reserve_terminal_slot",
]
