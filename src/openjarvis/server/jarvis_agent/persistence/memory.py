"""Context, opaque references and canonical events repository operations."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.persistence.codec import (
    decode_json,
    encode_json,
    row_dict,
)


class MemoryStoreMixin:
    def put_context(self, record: Mapping[str, Any]) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO jarvis_context(
                    partition_key, project_key, codex_thread_id, context_json,
                    updated_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(partition_key) DO UPDATE SET
                    context_json = excluded.context_json,
                    updated_at = excluded.updated_at,
                    expires_at = excluded.expires_at
                """,
                (
                    record["partition_key"],
                    record["project_key"],
                    record.get("codex_thread_id", ""),
                    encode_json(record["context"]),
                    record["updated_at"],
                    record["expires_at"],
                ),
            )

    def get_context(self, partition_key: str, now: float) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            record = row_dict(
                connection.execute(
                    """
                    SELECT * FROM jarvis_context
                    WHERE partition_key = ? AND expires_at > ?
                    """,
                    (partition_key, now),
                ).fetchone()
            )
            if record is not None:
                record["context"] = decode_json(record.pop("context_json")) or {}
            return record
        finally:
            connection.close()

    def delete_context(self, partition_key: str) -> bool:
        with self._transaction() as connection:
            result = connection.execute(
                "DELETE FROM jarvis_context WHERE partition_key = ?",
                (partition_key,),
            )
            return result.rowcount == 1

    def put_reference(self, record: Mapping[str, Any]) -> str:
        with self._transaction() as connection:
            existing = connection.execute(
                """
                SELECT reference_id FROM jarvis_references
                WHERE partition_key = ? AND source = ? AND kind = ? AND value_hash = ?
                """,
                (
                    record["partition_key"],
                    record["source"],
                    record["kind"],
                    record["value_hash"],
                ),
            ).fetchone()
            if existing is not None:
                connection.execute(
                    """
                    UPDATE jarvis_references SET metadata_json = ?, expires_at = ?
                    WHERE reference_id = ?
                    """,
                    (
                        encode_json(record.get("metadata", {})),
                        record["expires_at"],
                        existing["reference_id"],
                    ),
                )
                return str(existing["reference_id"])
            connection.execute(
                """
                INSERT INTO jarvis_references(
                    reference_id, partition_key, source, kind, value_hash,
                    provider_value, metadata_json, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["reference_id"],
                    record["partition_key"],
                    record["source"],
                    record["kind"],
                    record["value_hash"],
                    record["provider_value"],
                    encode_json(record.get("metadata", {})),
                    record["created_at"],
                    record["expires_at"],
                ),
            )
            return str(record["reference_id"])

    def get_reference(
        self, reference_id: str, partition_key: str, now: float
    ) -> dict[str, Any] | None:
        connection = self._connect()
        try:
            record = row_dict(
                connection.execute(
                    """
                    SELECT * FROM jarvis_references
                    WHERE reference_id = ? AND partition_key = ? AND expires_at > ?
                    """,
                    (reference_id, partition_key, now),
                ).fetchone()
            )
            if record is not None:
                record["metadata"] = decode_json(record.pop("metadata_json")) or {}
            return record
        finally:
            connection.close()

    def append_event(self, record: Mapping[str, Any]) -> int:
        with self._transaction() as connection:
            cursor = connection.execute(
                """
                INSERT INTO jarvis_agent_events(
                    event_id, event_type, session_id, action_id, job_id,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record["event_id"],
                    record["event_type"],
                    record.get("session_id"),
                    record.get("action_id"),
                    record.get("job_id"),
                    encode_json(record.get("payload", {})),
                    record["created_at"],
                ),
            )
            return int(cursor.lastrowid)

    def list_events(self, after: int, limit: int = 100) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            records = connection.execute(
                """
                SELECT * FROM jarvis_agent_events WHERE sequence > ?
                ORDER BY sequence ASC LIMIT ?
                """,
                (after, min(500, max(1, limit))),
            ).fetchall()
            result = []
            for item in records:
                value = dict(item)
                value["payload"] = decode_json(value.pop("payload_json")) or {}
                result.append(value)
            return result
        finally:
            connection.close()

    def list_thread_events(
        self,
        project_key: str,
        codex_thread_id: str,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Return the latest canonical events scoped to one Codex target."""

        connection = self._connect()
        try:
            records = connection.execute(
                """
                SELECT * FROM (
                    SELECT events.* FROM jarvis_agent_events AS events
                    JOIN jarvis_sessions AS sessions
                      ON sessions.session_id = events.session_id
                    WHERE sessions.project_key = ?
                      AND sessions.codex_thread_id = ?
                    ORDER BY events.sequence DESC
                    LIMIT ?
                ) ORDER BY sequence ASC
                """,
                (
                    project_key.strip(),
                    codex_thread_id.strip(),
                    min(500, max(1, limit)),
                ),
            ).fetchall()
            result = []
            for item in records:
                value = dict(item)
                value["payload"] = decode_json(value.pop("payload_json")) or {}
                result.append(value)
            return result
        finally:
            connection.close()
