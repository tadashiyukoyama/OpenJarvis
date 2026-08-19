from __future__ import annotations

from openjarvis.integrations.codex_protocol import (
    CodexConversationEvent,
    CodexTurnStatus,
)
from openjarvis.server.codex_sync_events import (
    codex_execution_payload,
    public_event_is_relevant,
)


def test_execution_payload_is_sanitized_ordered_and_machine_readable() -> None:
    event = CodexConversationEvent(
        method="item/started",
        event_id="edge-event-1",
        sequence=12,
        thread_id="thread-1",
        turn_id="turn-1",
        item_id="item-1",
        event_type="item_started",
        public_action_summary="Executando testes controlados.",
        terminal_status=CodexTurnStatus.RUNNING,
        metadata={"private": "not forwarded"},
    )

    assert public_event_is_relevant(event, "thread-1") is True
    assert codex_execution_payload(event, "thread-1") == {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "item_id": "item-1",
        "event_type": "item_started",
        "state": "running",
        "action_summary": "Executando testes controlados.",
        "event_id": "edge-event-1",
        "sequence": 12,
    }


def test_execution_payload_maps_terminal_state_without_inventing_details() -> None:
    event = CodexConversationEvent(
        method="turn/completed",
        thread_id="thread-1",
        turn_id="turn-1",
        event_type="turn_completed",
        terminal_status=CodexTurnStatus.FAILED,
    )

    assert codex_execution_payload(event, "thread-1") == {
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "item_id": None,
        "event_type": "turn_completed",
        "state": "failed",
    }
