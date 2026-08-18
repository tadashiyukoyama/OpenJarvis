"""Nested Codex approval persistence for Edge jobs."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.persistence.codec import decode_json, encode_json


class EdgeApprovalStoreMixin:
    def create_edge_approval(self, record: Mapping[str, Any]) -> dict[str, Any]:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO jarvis_edge_approvals(
                    approval_id, job_id, attempt_id, state, preview_json,
                    payload_hash, created_at, expires_at
                ) VALUES (?, ?, ?, 'AWAITING_APPROVAL', ?, ?, ?, ?)
                ON CONFLICT(approval_id) DO NOTHING
                """,
                (
                    record["approval_id"],
                    record["job_id"],
                    record["attempt_id"],
                    encode_json(record.get("preview") or {}),
                    record["payload_hash"],
                    record["created_at"],
                    record["expires_at"],
                ),
            )
            row = connection.execute(
                "SELECT * FROM jarvis_edge_approvals WHERE approval_id = ?",
                (record["approval_id"],),
            ).fetchone()
            return self._edge_approval_record(row)

    @staticmethod
    def _edge_approval_record(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["preview"] = decode_json(value.pop("preview_json")) or {}
        return value

    def get_edge_approval(self, approval_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM jarvis_edge_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            return self._edge_approval_record(row) if row is not None else None
        finally:
            connection.close()

    def edge_approvals_for_jobs(
        self, job_ids: list[str], *, states: tuple[str, ...]
    ) -> list[dict[str, Any]]:
        if not job_ids or not states:
            return []
        job_placeholders = ",".join("?" for _ in job_ids)
        state_placeholders = ",".join("?" for _ in states)
        connection = self._connect()
        try:
            rows = connection.execute(
                f"""
                SELECT * FROM jarvis_edge_approvals
                WHERE job_id IN ({job_placeholders})
                  AND state IN ({state_placeholders})
                ORDER BY created_at ASC
                """,
                (*job_ids, *states),
            ).fetchall()
            return [self._edge_approval_record(row) for row in rows]
        finally:
            connection.close()

    def decide_edge_approval(
        self,
        *,
        approval_id: str,
        payload_hash: str,
        decision: str,
        now: float,
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            row = connection.execute(
                "SELECT * FROM jarvis_edge_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            if row is None:
                return None
            if row["payload_hash"] != payload_hash:
                raise sqlite3.IntegrityError("APPROVAL_PAYLOAD_MISMATCH")
            if row["state"] != "AWAITING_APPROVAL":
                return self._edge_approval_record(row)
            state = (
                "EXPIRED"
                if row["expires_at"] <= now
                else ("APPROVED" if decision == "approve" else "DENIED")
            )
            connection.execute(
                """
                UPDATE jarvis_edge_approvals
                SET state = ?, decision = ?, decided_at = ?
                WHERE approval_id = ?
                """,
                (state, decision, now, approval_id),
            )
            updated = connection.execute(
                "SELECT * FROM jarvis_edge_approvals WHERE approval_id = ?",
                (approval_id,),
            ).fetchone()
            return self._edge_approval_record(updated)


__all__ = ["EdgeApprovalStoreMixin"]
