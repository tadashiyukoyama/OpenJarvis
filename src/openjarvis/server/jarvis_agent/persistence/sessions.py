"""Session and committed-turn repository operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.persistence.codec import row_dict


class SessionStoreMixin:
    def create_session(self, record: Mapping[str, Any]) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO jarvis_sessions(
                    session_id, generation, project_key, codex_thread_id,
                    manifest_version, state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["session_id"],
                    record["generation"],
                    record["project_key"],
                    record.get("codex_thread_id", ""),
                    record["manifest_version"],
                    record["state"],
                    record["created_at"],
                    record["created_at"],
                ),
            )

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            return row_dict(
                connection.execute(
                    "SELECT * FROM jarvis_sessions WHERE session_id = ?",
                    (session_id,),
                ).fetchone()
            )
        finally:
            connection.close()

    def close_session(self, session_id: str, generation: int, now: float) -> bool:
        with self._transaction() as connection:
            result = connection.execute(
                """
                UPDATE jarvis_sessions
                SET state = 'CLOSED', closed_at = ?, updated_at = ?
                WHERE session_id = ? AND generation = ? AND state = 'ACTIVE'
                """,
                (now, now, session_id, generation),
            )
            connection.execute(
                """
                UPDATE jarvis_actions
                    SET state = 'CANCELLED', payload_json = NULL,
                        preview_json = '{}',
                    updated_at = ?, error_code = 'SESSION_CLOSED'
                WHERE session_id = ?
                  AND state IN ('PROPOSED', 'AWAITING_APPROVAL', 'APPROVED')
                """,
                (now, session_id),
            )
            return result.rowcount == 1

    def add_turn(self, record: Mapping[str, Any]) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO jarvis_turns(
                    turn_id, session_id, generation, transcript_text,
                    transcript_hash, committed_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    record["turn_id"],
                    record["session_id"],
                    record["generation"],
                    record["transcript_text"],
                    record["transcript_hash"],
                    record["committed_at"],
                ),
            )

    def get_turn(self, turn_id: str) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            return row_dict(
                connection.execute(
                    "SELECT * FROM jarvis_turns WHERE turn_id = ?", (turn_id,)
                ).fetchone()
            )
        finally:
            connection.close()

    def recent_unredacted_turns(
        self,
        *,
        session_id: str,
        generation: int,
        through_turn_id: str,
        committed_after: float,
        limit: int,
    ) -> list[dict[str, Any]]:
        """Return a bounded, ordered voice window ending at one committed turn."""

        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT turn_id, session_id, generation, transcript_text,
                       transcript_hash, committed_at, redacted_at
                FROM jarvis_turns
                WHERE session_id = ? AND generation = ?
                  AND transcript_text IS NOT NULL
                  AND committed_at >= ?
                  AND committed_at <= (
                      SELECT committed_at FROM jarvis_turns WHERE turn_id = ?
                  )
                  AND rowid <= (
                      SELECT rowid FROM jarvis_turns WHERE turn_id = ?
                  )
                ORDER BY committed_at DESC, rowid DESC
                LIMIT ?
                """,
                (
                    session_id,
                    generation,
                    committed_after,
                    through_turn_id,
                    through_turn_id,
                    limit,
                ),
            ).fetchall()
            return [row_dict(row) for row in reversed(rows)]
        finally:
            connection.close()

    def redact_turns(self, turn_ids: list[str] | tuple[str, ...], now: float) -> None:
        unique_ids = tuple(dict.fromkeys(turn_ids))
        if not unique_ids:
            return
        placeholders = ", ".join("?" for _ in unique_ids)
        with self._transaction() as connection:
            connection.execute(
                f"""
                UPDATE jarvis_turns
                SET transcript_text = NULL, redacted_at = ?
                WHERE turn_id IN ({placeholders})
                """,
                (now, *unique_ids),
            )

    def redact_turn(self, turn_id: str, now: float) -> None:
        self.redact_turns((turn_id,), now)
