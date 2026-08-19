"""Atomic persistence for the bounded non-terminal Edge frame partition."""

from __future__ import annotations

import sqlite3
import time

from openjarvis.edge_worker.spool_errors import EdgeSpoolCapacityError


def persist_normal_outbound(
    connection: sqlite3.Connection,
    *,
    event_id: str,
    sequence: int,
    wire_json: str,
    max_frames: int,
    max_bytes: int,
) -> None:
    """Persist one idempotent normal frame inside the caller transaction."""
    existing = connection.execute(
        "SELECT sequence, wire_json, terminal_job_id FROM outbound_frames "
        "WHERE event_id = ?",
        (event_id,),
    ).fetchone()
    if existing is not None:
        identity_changed = (
            int(existing["sequence"]) != sequence
            or existing["wire_json"] != wire_json
            or existing["terminal_job_id"] is not None
        )
        if identity_changed:
            raise ValueError("Edge outbound event identity mismatch")
        return

    wire_bytes = len(wire_json.encode("utf-8"))
    stats = connection.execute(
        "SELECT COUNT(*) AS frame_count, "
        "COALESCE(SUM(LENGTH(CAST(wire_json AS BLOB))), 0) AS byte_count "
        "FROM outbound_frames WHERE terminal_job_id IS NULL"
    ).fetchone()
    if (
        int(stats["frame_count"]) >= max_frames
        or int(stats["byte_count"]) + wire_bytes > max_bytes
    ):
        raise EdgeSpoolCapacityError(
            "Edge outbound spool capacity reached; durable event was not queued"
        )
    connection.execute(
        "INSERT INTO outbound_frames"
        "(event_id, sequence, wire_json, created_at) VALUES (?, ?, ?, ?)",
        (event_id, sequence, wire_json, time.time()),
    )


__all__ = ["persist_normal_outbound"]
