"""Durable provider-operation and webhook reconciliation ledger."""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.persistence.codec import decode_json, encode_json
from openjarvis.server.jarvis_agent.persistence.provider_outcomes import (
    apply_provider_outcome,
    operation_action_id,
)


class ProviderStoreMixin:
    def accept_external_operation(
        self,
        *,
        action_id: str,
        provider: str,
        resource_type: str,
        resource_id: str,
        result: Mapping[str, Any],
        summary: str,
        now: float,
    ) -> dict[str, Any] | None:
        with self._transaction() as connection:
            connection.execute(
                """
                UPDATE jarvis_actions
                SET state = 'ACCEPTED', updated_at = ?, result_json = ?,
                    result_summary = ?, error_code = NULL,
                    payload_json = NULL, preview_json = '{}'
                WHERE action_id = ?
                """,
                (now, encode_json(result), summary[:2_000], action_id),
            )
            connection.execute(
                """
                INSERT INTO jarvis_external_operations(
                    action_id, provider, resource_type, resource_id,
                    state, created_at, updated_at
                ) VALUES (?, ?, ?, ?, 'ACCEPTED', ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    state = excluded.state, updated_at = excluded.updated_at
                """,
                (action_id, provider, resource_type, resource_id, now, now),
            )
            latest = connection.execute(
                """
                SELECT e.resource_sequence, e.received_at, o.next_state,
                       o.result_json, o.result_summary, o.error_code
                FROM jarvis_provider_events AS e
                JOIN jarvis_provider_event_outcomes AS o USING(event_id)
                WHERE e.provider = ? AND e.resource_type = ?
                  AND e.resource_id = ? AND e.disposition != 'out_of_order'
                ORDER BY e.resource_sequence DESC, e.received_at DESC
                LIMIT 1
                """,
                (provider, resource_type, resource_id),
            ).fetchone()
            if latest is not None:
                connection.execute(
                    """
                    UPDATE jarvis_provider_events SET action_id = ?
                    WHERE provider = ? AND resource_type = ? AND resource_id = ?
                      AND action_id IS NULL
                    """,
                    (action_id, provider, resource_type, resource_id),
                )
                apply_provider_outcome(
                    connection,
                    action_id=action_id,
                    next_state=str(latest["next_state"]),
                    result=decode_json(latest["result_json"]) or {},
                    summary=str(latest["result_summary"]),
                    error_code=latest["error_code"],
                    sequence=int(latest["resource_sequence"]),
                    now=max(now, float(latest["received_at"])),
                )
            return self.get_action(action_id, connection=connection)

    def record_provider_event(
        self,
        *,
        delivery_id: str,
        event_id: str,
        provider: str,
        event_name: str,
        resource_type: str,
        resource_id: str,
        resource_sequence: int,
        resource_version: str,
        occurred_at: str,
        received_at: float,
        next_state: str,
        result: Mapping[str, Any],
        summary: str,
        error_code: str | None,
    ) -> dict[str, Any]:
        with self._transaction() as connection:
            duplicate = connection.execute(
                """
                SELECT delivery_id, event_id, disposition, action_id,
                       provider, resource_type, resource_id, resource_sequence
                FROM jarvis_provider_events
                WHERE delivery_id = ? OR event_id = ?
                """,
                (delivery_id, event_id),
            ).fetchone()
            if duplicate is not None:
                transitioned = False
                action_id = duplicate["action_id"] or operation_action_id(
                    connection,
                    str(duplicate["provider"]),
                    str(duplicate["resource_type"]),
                    str(duplicate["resource_id"]),
                )
                if action_id is not None and duplicate["action_id"] is None:
                    connection.execute(
                        """
                        UPDATE jarvis_provider_events
                        SET action_id = ? WHERE event_id = ?
                        """,
                        (action_id, duplicate["event_id"]),
                    )
                    outcome = connection.execute(
                        """
                        SELECT next_state, result_json, result_summary, error_code
                        FROM jarvis_provider_event_outcomes WHERE event_id = ?
                        """,
                        (duplicate["event_id"],),
                    ).fetchone()
                    if (
                        outcome is not None
                        and duplicate["disposition"] != "out_of_order"
                    ):
                        transitioned = apply_provider_outcome(
                            connection,
                            action_id=str(action_id),
                            next_state=str(outcome["next_state"]),
                            result=decode_json(outcome["result_json"]) or {},
                            summary=str(outcome["result_summary"]),
                            error_code=outcome["error_code"],
                            sequence=int(duplicate["resource_sequence"]),
                            now=received_at,
                        )
                return {
                    "disposition": "duplicate",
                    "action": self._action_for_event(connection, action_id),
                    "transitioned": transitioned,
                }
            sequence = connection.execute(
                """
                SELECT last_sequence FROM jarvis_provider_sequences
                WHERE provider = ? AND resource_type = ? AND resource_id = ?
                """,
                (provider, resource_type, resource_id),
            ).fetchone()
            stale = (
                sequence is not None and resource_sequence <= sequence["last_sequence"]
            )
            gap = (
                sequence is not None
                and resource_sequence > sequence["last_sequence"] + 1
            )
            action_id = operation_action_id(
                connection, provider, resource_type, resource_id
            )
            disposition = (
                "out_of_order"
                if stale
                else ("accepted_with_gap" if gap else "accepted")
            )
            connection.execute(
                """
                INSERT INTO jarvis_provider_events(
                    delivery_id, event_id, provider, event_name, resource_type,
                    resource_id, resource_sequence, resource_version,
                    occurred_at, received_at, disposition, action_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    delivery_id,
                    event_id,
                    provider,
                    event_name,
                    resource_type,
                    resource_id,
                    resource_sequence,
                    resource_version,
                    occurred_at,
                    received_at,
                    disposition,
                    action_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO jarvis_provider_event_outcomes(
                    event_id, next_state, result_json, result_summary, error_code
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    next_state,
                    encode_json(result),
                    summary[:2_000],
                    error_code,
                ),
            )
            if stale:
                return {
                    "disposition": disposition,
                    "action": self._action_for_event(connection, action_id),
                    "transitioned": False,
                }
            connection.execute(
                """
                INSERT INTO jarvis_provider_sequences(
                    provider, resource_type, resource_id, last_sequence,
                    resource_version, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, resource_type, resource_id) DO UPDATE SET
                    last_sequence = excluded.last_sequence,
                    resource_version = excluded.resource_version,
                    updated_at = excluded.updated_at
                """,
                (
                    provider,
                    resource_type,
                    resource_id,
                    resource_sequence,
                    resource_version,
                    received_at,
                ),
            )
            transitioned = False
            if action_id is not None:
                transitioned = apply_provider_outcome(
                    connection,
                    action_id=action_id,
                    next_state=next_state,
                    result=result,
                    summary=summary,
                    error_code=error_code,
                    sequence=resource_sequence,
                    now=received_at,
                )
            return {
                "disposition": disposition,
                "action": self._action_for_event(connection, action_id),
                "transitioned": transitioned,
            }

    def _action_for_event(
        self, connection: sqlite3.Connection, action_id: str | None
    ) -> dict[str, Any] | None:
        if action_id is None:
            return None
        row = connection.execute(
            "SELECT * FROM jarvis_actions WHERE action_id = ?", (action_id,)
        ).fetchone()
        return self._action_record(row) if row is not None else None
