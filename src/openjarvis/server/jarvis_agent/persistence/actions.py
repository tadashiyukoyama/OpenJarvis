"""Actions, approvals and asynchronous-job repository operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.persistence.codec import (
    decode_json,
    encode_json,
    row_dict,
)


class ActionStoreMixin:
    def create_action(self, record: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        with self._transaction() as connection:
            duplicate = connection.execute(
                """
                SELECT * FROM jarvis_actions
                WHERE session_id = ? AND function_call_id = ? AND payload_hash = ?
                """,
                (
                    record["session_id"],
                    record["function_call_id"],
                    record["payload_hash"],
                ),
            ).fetchone()
            if duplicate is not None:
                return self._action_record(duplicate), False
            if record["state"] == "AWAITING_APPROVAL":
                pending = connection.execute(
                    """
                    SELECT action_id FROM jarvis_actions
                    WHERE session_id = ? AND state = 'AWAITING_APPROVAL'
                    """,
                    (record["session_id"],),
                ).fetchone()
                if pending is not None:
                    raise sqlite3.IntegrityError("ACTION_PENDING")
            connection.execute(
                """
                INSERT INTO jarvis_actions(
                    action_id, session_id, generation, function_call_id, tool_id,
                    payload_hash, payload_json, preview_json, state, created_at,
                    expires_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["action_id"],
                    record["session_id"],
                    record["generation"],
                    record["function_call_id"],
                    record["tool_id"],
                    record["payload_hash"],
                    encode_json(record["payload"]),
                    encode_json(record["preview"]),
                    record["state"],
                    record["created_at"],
                    record.get("expires_at"),
                    record["created_at"],
                ),
            )
            return self.get_action(record["action_id"], connection=connection), True

    def get_action_by_request(
        self,
        *,
        session_id: str,
        function_call_id: str,
        payload_hash: str,
    ) -> dict[str, Any] | None:
        """Return an exact idempotent action without creating a second one."""

        connection = self._connect()
        try:
            row = connection.execute(
                """
                SELECT * FROM jarvis_actions
                WHERE session_id = ? AND function_call_id = ? AND payload_hash = ?
                """,
                (session_id, function_call_id, payload_hash),
            ).fetchone()
            return self._action_record(row) if row is not None else None
        finally:
            connection.close()

    @staticmethod
    def _action_record(row: sqlite3.Row) -> dict[str, Any]:
        record = dict(row)
        record["payload"] = decode_json(record.pop("payload_json"))
        record["preview"] = decode_json(record.pop("preview_json")) or {}
        record["result"] = decode_json(record.pop("result_json"))
        return record

    def get_action(
        self, action_id: str, *, connection: sqlite3.Connection | None = None
    ) -> dict[str, Any] | None:
        own_connection = connection is None
        connection = connection or self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM jarvis_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            return self._action_record(row) if row is not None else None
        finally:
            if own_connection:
                connection.close()

    def pending_action_ids(self, session_id: str) -> list[str]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT action_id FROM jarvis_actions
                WHERE session_id = ?
                  AND state IN ('PROPOSED', 'AWAITING_APPROVAL', 'APPROVED')
                """,
                (session_id,),
            ).fetchall()
            return [str(row["action_id"]) for row in rows]
        finally:
            connection.close()

    def decide_action(
        self,
        *,
        approval_id: str,
        action_id: str,
        session_id: str,
        payload_hash: str,
        decision: str,
        now: float,
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            record = connection.execute(
                "SELECT * FROM jarvis_actions WHERE action_id = ?", (action_id,)
            ).fetchone()
            if record is None:
                return None
            if not self._approval_matches(record, session_id, payload_hash):
                raise sqlite3.IntegrityError("APPROVAL_PAYLOAD_MISMATCH")
            if record["state"] != "AWAITING_APPROVAL":
                return self.get_action(action_id, connection=connection)
            if record["expires_at"] is not None and record["expires_at"] <= now:
                self._expire_approval(connection, action_id, now)
                return self.get_action(action_id, connection=connection)
            next_state = "APPROVED" if decision == "approve" else "DENIED"
            connection.execute(
                """
                UPDATE jarvis_actions SET state = ?, updated_at = ?
                WHERE action_id = ?
                """,
                (next_state, now, action_id),
            )
            self._insert_approval(
                connection=connection,
                approval_id=approval_id,
                action_id=action_id,
                session_id=session_id,
                function_call_id=str(record["function_call_id"]),
                payload_hash=payload_hash,
                decision=decision,
                now=now,
            )
            if next_state == "DENIED":
                connection.execute(
                    """
                    UPDATE jarvis_actions
                    SET payload_json = NULL, preview_json = '{}'
                    WHERE action_id = ?
                    """,
                    (action_id,),
                )
            return self.get_action(action_id, connection=connection)

    @staticmethod
    def _approval_matches(
        record: sqlite3.Row, session_id: str, payload_hash: str
    ) -> bool:
        return (
            record["session_id"] == session_id
            and record["payload_hash"] == payload_hash
        )

    @staticmethod
    def _expire_approval(
        connection: sqlite3.Connection, action_id: str, now: float
    ) -> None:
        connection.execute(
            """
            UPDATE jarvis_actions
            SET state = 'EXPIRED', payload_json = NULL,
                preview_json = '{}', updated_at = ?
            WHERE action_id = ?
            """,
            (now, action_id),
        )

    @staticmethod
    def _insert_approval(
        *,
        connection: sqlite3.Connection,
        approval_id: str,
        action_id: str,
        session_id: str,
        function_call_id: str,
        payload_hash: str,
        decision: str,
        now: float,
    ) -> None:
        connection.execute(
            """
            INSERT INTO jarvis_approvals(
                approval_id, action_id, session_id, function_call_id,
                payload_hash, decision, decided_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                action_id,
                session_id,
                function_call_id,
                payload_hash,
                decision,
                now,
            ),
        )

    def update_action(
        self,
        action_id: str,
        state: str,
        *,
        now: float,
        result: Mapping[str, Any] | None = None,
        summary: str = "",
        error_code: str | None = None,
        clear_sensitive: bool = False,
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE jarvis_actions SET state = ?, updated_at = ?, result_json = ?,
                    result_summary = ?, error_code = ?,
                    payload_json = CASE WHEN ? THEN NULL ELSE payload_json END,
                    preview_json = CASE WHEN ? THEN '{}' ELSE preview_json END
                WHERE action_id = ?
                """,
                (
                    state,
                    now,
                    encode_json(result),
                    summary[:2000],
                    error_code,
                    int(clear_sensitive),
                    int(clear_sensitive),
                    action_id,
                ),
            )
            return self.get_action(action_id, connection=connection)

    def transition_action(
        self,
        action_id: str,
        *,
        expected_state: str,
        next_state: str,
        now: float,
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            changed = connection.execute(
                """
                UPDATE jarvis_actions SET state = ?, updated_at = ?
                WHERE action_id = ? AND state = ?
                """,
                (next_state, now, action_id, expected_state),
            ).rowcount
            if changed != 1:
                return None
            return self.get_action(action_id, connection=connection)

    def create_job(self, record: Mapping[str, Any]) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO jarvis_jobs(
                    job_id, action_id, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    record["job_id"],
                    record["action_id"],
                    record["state"],
                    record["created_at"],
                    record["created_at"],
                ),
            )

    def update_job(
        self,
        job_id: str,
        state: str,
        *,
        now: float,
        result: Mapping[str, Any] | None = None,
        summary: str = "",
        error_code: str | None = None,
    ) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE jarvis_jobs SET state = ?, updated_at = ?, result_json = ?,
                    result_summary = ?, error_code = ? WHERE job_id = ?
                """,
                (state, now, encode_json(result), summary[:2000], error_code, job_id),
            )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            record = row_dict(
                connection.execute(
                    "SELECT * FROM jarvis_jobs WHERE job_id = ?", (job_id,)
                ).fetchone()
            )
            if record is not None:
                record["result"] = decode_json(record.pop("result_json"))
            return record
        finally:
            connection.close()
