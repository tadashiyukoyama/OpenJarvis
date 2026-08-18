"""Transactional helpers for applying durable provider outcomes."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.persistence.codec import decode_json, encode_json


def operation_action_id(
    connection: sqlite3.Connection,
    provider: str,
    resource_type: str,
    resource_id: str,
) -> str | None:
    row = connection.execute(
        """
        SELECT action_id FROM jarvis_external_operations
        WHERE provider = ? AND resource_type = ? AND resource_id = ?
        """,
        (provider, resource_type, resource_id),
    ).fetchone()
    return str(row["action_id"]) if row is not None else None


def apply_provider_outcome(
    connection: sqlite3.Connection,
    *,
    action_id: str,
    next_state: str,
    result: Mapping[str, Any],
    summary: str,
    error_code: str | None,
    sequence: int,
    now: float,
) -> bool:
    action = connection.execute(
        "SELECT state, result_json FROM jarvis_actions WHERE action_id = ?",
        (action_id,),
    ).fetchone()
    if action is None or action["state"] != "ACCEPTED":
        return False
    previous = decode_json(action["result_json"]) if action is not None else None
    merged = dict(previous or {})
    merged.update(result)
    updated = connection.execute(
        """
        UPDATE jarvis_actions
        SET state = ?, updated_at = ?, result_json = ?,
            result_summary = ?, error_code = ?
        WHERE action_id = ? AND state = 'ACCEPTED'
        """,
        (
            next_state,
            now,
            encode_json(merged),
            summary[:2_000],
            error_code,
            action_id,
        ),
    )
    if updated.rowcount != 1:
        return False
    connection.execute(
        """
        UPDATE jarvis_external_operations
        SET state = ?, last_sequence = ?, updated_at = ?
        WHERE action_id = ? AND state = 'ACCEPTED'
        """,
        (next_state, sequence, now, action_id),
    )
    return True
