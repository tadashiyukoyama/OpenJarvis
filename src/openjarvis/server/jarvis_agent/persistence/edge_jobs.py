"""Durable Edge assignments, attempts and nested approval operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.persistence.codec import decode_json, encode_json


class EdgeJobStoreMixin:
    @staticmethod
    def _edge_assignment_record(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["result"] = decode_json(value.pop("result_json"))
        return value

    def create_edge_assignment(
        self, record: Mapping[str, Any]
    ) -> tuple[dict[str, Any], bool]:
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM jarvis_edge_assignments WHERE job_id = ?",
                (record["job_id"],),
            ).fetchone()
            if existing is not None:
                if (
                    existing["tool_id"] != record["tool_id"]
                    or existing["payload_hash"] != record["payload_hash"]
                ):
                    raise sqlite3.IntegrityError("EDGE_JOB_INVALID")
                return self._edge_assignment_record(existing), False
            connection.execute(
                """
                INSERT INTO jarvis_edge_assignments(
                    job_id, action_id, device_id, attempt_id, attempt_number,
                    tool_id, payload_hash, state, offered_at, lease_expires_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, 1, ?, ?, 'OFFERED', ?, ?, ?)
                """,
                (
                    record["job_id"],
                    record.get("action_id"),
                    record["device_id"],
                    record["attempt_id"],
                    record["tool_id"],
                    record["payload_hash"],
                    record["offered_at"],
                    record["lease_expires_at"],
                    record["offered_at"],
                ),
            )
            connection.execute(
                """
                INSERT INTO jarvis_edge_attempts(
                    attempt_id, job_id, device_id, attempt_number, state,
                    lease_expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, 1, 'OFFERED', ?, ?, ?)
                """,
                (
                    record["attempt_id"],
                    record["job_id"],
                    record["device_id"],
                    record["lease_expires_at"],
                    record["offered_at"],
                    record["offered_at"],
                ),
            )
            return self.get_edge_assignment(
                record["job_id"], connection=connection
            ), True

    def get_edge_assignment(
        self, job_id: str, *, connection: sqlite3.Connection | None = None
    ) -> dict[str, Any] | None:
        own_connection = connection is None
        connection = connection or self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM jarvis_edge_assignments WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            return self._edge_assignment_record(row) if row is not None else None
        finally:
            if own_connection:
                connection.close()

    def edge_assignments_for_device(
        self, device_id: str, *, states: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        if not states:
            return []
        placeholders = ",".join("?" for _ in states)
        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT * FROM jarvis_edge_assignments
                WHERE device_id = ? AND state IN ({placeholders})
                ORDER BY offered_at ASC
                """,
                (device_id, *states),
            ).fetchall()
            return [self._edge_assignment_record(row) for row in rows]
        finally:
            connection.close()

    def transition_edge_assignment(
        self,
        *,
        job_id: str,
        attempt_id: str,
        expected_states: tuple[str, ...],
        next_state: str,
        now: float,
        accepted_at: float | None = None,
    ) -> dict[str, Any] | None:
        placeholders = ",".join("?" for _ in expected_states)
        with self._transaction() as connection:
            parameters: list[Any] = [next_state, now, accepted_at, job_id, attempt_id]
            parameters.extend(expected_states)
            changed = connection.execute(
                f"""
                UPDATE jarvis_edge_assignments
                SET state = ?, updated_at = ?,
                    accepted_at = COALESCE(accepted_at, ?)
                WHERE job_id = ? AND attempt_id = ?
                  AND state IN ({placeholders})
                """,
                tuple(parameters),
            ).rowcount
            if changed != 1:
                return None
            connection.execute(
                """
                UPDATE jarvis_edge_attempts SET state = ?, updated_at = ?
                WHERE attempt_id = ?
                """,
                (next_state, now, attempt_id),
            )
            return self.get_edge_assignment(job_id, connection=connection)

    def complete_edge_assignment(
        self,
        *,
        job_id: str,
        attempt_id: str,
        terminal_event_id: str,
        state: str,
        now: float,
        result: Mapping[str, Any] | None,
        summary: str,
        error_code: str | None,
        sensitive_purge_at: float | None,
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            current = connection.execute(
                "SELECT * FROM jarvis_edge_assignments WHERE job_id = ?",
                (job_id,),
            ).fetchone()
            if current is None or current["attempt_id"] != attempt_id:
                return None
            if current["terminal_event_id"]:
                return self._edge_assignment_record(current)
            connection.execute(
                """
                UPDATE jarvis_edge_assignments
                SET state = ?, updated_at = ?, terminal_event_id = ?,
                    result_json = ?, result_summary = ?, error_code = ?,
                    sensitive_purge_at = ?
                WHERE job_id = ? AND attempt_id = ?
                """,
                (
                    state,
                    now,
                    terminal_event_id,
                    encode_json(result),
                    summary[:2_000],
                    error_code,
                    sensitive_purge_at,
                    job_id,
                    attempt_id,
                ),
            )
            connection.execute(
                """
                UPDATE jarvis_edge_attempts SET state = ?, updated_at = ?
                WHERE attempt_id = ?
                """,
                (state, now, attempt_id),
            )
            return self.get_edge_assignment(job_id, connection=connection)


__all__ = ["EdgeJobStoreMixin"]
