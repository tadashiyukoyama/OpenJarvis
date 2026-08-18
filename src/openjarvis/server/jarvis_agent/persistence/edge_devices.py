"""Device registry, sequence cursors and Edge event ledger operations."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from typing import Any

from openjarvis.server.jarvis_agent.persistence.codec import (
    decode_json,
    encode_json,
    row_dict,
)


class EdgeDeviceStoreMixin:
    def upsert_edge_device(self, record: Mapping[str, Any]) -> dict[str, Any]:
        with self._transaction() as connection:
            connection.execute(
                """
                INSERT INTO jarvis_edge_devices(
                    device_id, status, revoked, capabilities_json, metadata_json,
                    current_credential_fingerprint,
                    previous_credential_fingerprint,
                    previous_credential_expires_at, connected_at, last_seen_at,
                    disconnected_at, last_error_code, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, NULL, ?)
                ON CONFLICT(device_id) DO UPDATE SET
                    status = excluded.status,
                    capabilities_json = excluded.capabilities_json,
                    metadata_json = excluded.metadata_json,
                    current_credential_fingerprint =
                        excluded.current_credential_fingerprint,
                    previous_credential_fingerprint =
                        excluded.previous_credential_fingerprint,
                    previous_credential_expires_at =
                        excluded.previous_credential_expires_at,
                    connected_at = excluded.connected_at,
                    last_seen_at = excluded.last_seen_at,
                    disconnected_at = NULL,
                    last_error_code = NULL,
                    updated_at = excluded.updated_at
                """,
                (
                    record["device_id"],
                    record.get("status", "ONLINE"),
                    int(bool(record.get("revoked", False))),
                    encode_json(sorted(set(record.get("capabilities") or []))),
                    encode_json(record.get("metadata") or {}),
                    record.get("current_credential_fingerprint", ""),
                    record.get("previous_credential_fingerprint", ""),
                    record.get("previous_credential_expires_at"),
                    record.get("connected_at"),
                    record.get("last_seen_at"),
                    record["updated_at"],
                ),
            )
            connection.execute(
                """
                INSERT INTO jarvis_edge_sequences(device_id, updated_at)
                VALUES (?, ?)
                ON CONFLICT(device_id) DO NOTHING
                """,
                (record["device_id"], record["updated_at"]),
            )
            return self.get_edge_device(record["device_id"], connection=connection)

    @staticmethod
    def _device_record(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["revoked"] = bool(value["revoked"])
        value["capabilities"] = decode_json(value.pop("capabilities_json")) or []
        value["metadata"] = decode_json(value.pop("metadata_json")) or {}
        return value

    def get_edge_device(
        self, device_id: str, *, connection: sqlite3.Connection | None = None
    ) -> dict[str, Any] | None:
        own_connection = connection is None
        connection = connection or self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM jarvis_edge_devices WHERE device_id = ?",
                (device_id,),
            ).fetchone()
            return self._device_record(row) if row is not None else None
        finally:
            if own_connection:
                connection.close()

    def mark_edge_device_offline(
        self, device_id: str, *, now: float, error_code: str | None = None
    ) -> None:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE jarvis_edge_devices
                SET status = 'OFFLINE', disconnected_at = ?, updated_at = ?,
                    last_error_code = ?
                WHERE device_id = ?
                """,
                (now, now, error_code, device_id),
            )

    def touch_edge_device(self, device_id: str, *, now: float) -> bool:
        with self._transaction() as connection:
            changed = connection.execute(
                """
                UPDATE jarvis_edge_devices
                SET last_seen_at = ?, updated_at = ?
                WHERE device_id = ? AND revoked = 0
                """,
                (now, now, device_id),
            ).rowcount
            return changed == 1

    def revoke_edge_device(self, device_id: str, *, now: float) -> bool:
        with self._transaction() as connection:
            changed = connection.execute(
                """
                UPDATE jarvis_edge_devices
                SET revoked = 1, status = 'REVOKED', disconnected_at = ?,
                    updated_at = ?, last_error_code = 'DEVICE_REVOKED'
                WHERE device_id = ?
                """,
                (now, now, device_id),
            ).rowcount
            return changed == 1

    def edge_sequences(self, device_id: str) -> dict[str, int]:
        connection = self._connect()
        try:
            row = row_dict(
                connection.execute(
                    """
                    SELECT inbound_sequence, outbound_sequence
                    FROM jarvis_edge_sequences WHERE device_id = ?
                    """,
                    (device_id,),
                ).fetchone()
            )
            return {
                "inbound_sequence": int((row or {}).get("inbound_sequence", 0)),
                "outbound_sequence": int((row or {}).get("outbound_sequence", 0)),
            }
        finally:
            connection.close()

    def next_edge_outbound_sequence(self, device_id: str, *, now: float) -> int:
        with self._transaction() as connection:
            changed = connection.execute(
                """
                UPDATE jarvis_edge_sequences
                SET outbound_sequence = outbound_sequence + 1, updated_at = ?
                WHERE device_id = ?
                """,
                (now, device_id),
            ).rowcount
            if changed != 1:
                raise sqlite3.IntegrityError("EDGE_DEVICE_UNKNOWN")
            row = connection.execute(
                """
                SELECT outbound_sequence FROM jarvis_edge_sequences
                WHERE device_id = ?
                """,
                (device_id,),
            ).fetchone()
            return int(row["outbound_sequence"])

    def record_edge_event(
        self,
        *,
        event_id: str,
        device_id: str,
        direction: str,
        sequence: int,
        event_type: str,
        job_id: str | None,
        payload_hash: str,
        metadata: Mapping[str, Any],
        occurred_at: str,
        received_at: float,
    ) -> bool:
        if direction not in {"inbound", "outbound"}:
            raise ValueError("invalid Edge event direction")
        with self._transaction() as connection:
            duplicate = connection.execute(
                "SELECT 1 FROM jarvis_edge_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if duplicate is not None:
                return False
            if direction == "inbound":
                cursor = connection.execute(
                    """
                    SELECT inbound_sequence FROM jarvis_edge_sequences
                    WHERE device_id = ?
                    """,
                    (device_id,),
                ).fetchone()
                if cursor is None or sequence <= int(cursor["inbound_sequence"]):
                    raise sqlite3.IntegrityError("EDGE_SEQUENCE_INVALID")
            connection.execute(
                """
                INSERT INTO jarvis_edge_events(
                    event_id, device_id, direction, sequence, event_type, job_id,
                    payload_hash, metadata_json, occurred_at, received_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    device_id,
                    direction,
                    sequence,
                    event_type,
                    job_id,
                    payload_hash,
                    encode_json(metadata),
                    occurred_at,
                    received_at,
                ),
            )
            if direction == "inbound":
                connection.execute(
                    """
                    UPDATE jarvis_edge_sequences
                    SET inbound_sequence = ?, updated_at = ?
                    WHERE device_id = ?
                    """,
                    (sequence, received_at, device_id),
                )
            return True

    def edge_outbound_events_after(
        self, device_id: str, sequence: int, *, limit: int = 100
    ) -> Sequence[dict[str, Any]]:
        connection = self._connect()
        try:
            rows = connection.execute(
                """
                SELECT * FROM jarvis_edge_events
                WHERE device_id = ? AND direction = 'outbound' AND sequence > ?
                ORDER BY sequence ASC LIMIT ?
                """,
                (device_id, sequence, min(500, max(1, limit))),
            ).fetchall()
            values: list[dict[str, Any]] = []
            for row in rows:
                value = dict(row)
                value["metadata"] = decode_json(value.pop("metadata_json")) or {}
                values.append(value)
            return values
        finally:
            connection.close()


__all__ = ["EdgeDeviceStoreMixin"]
