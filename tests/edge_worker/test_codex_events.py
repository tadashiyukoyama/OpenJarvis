from __future__ import annotations

import asyncio
from typing import Any

import pytest

from openjarvis.edge_worker.codex_events import (
    CodexEventRelay,
    public_codex_event_payload,
)
from openjarvis.integrations.codex_protocol import (
    CodexConversationEvent,
    CodexHistoryMessage,
    CodexTurnStatus,
)


def _event(**overrides: Any) -> CodexConversationEvent:
    values: dict[str, Any] = {
        "method": "item/agentMessage/delta",
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "item_id": "item-1",
        "event_type": "text_delta",
        "public_text_delta": "Olá",
    }
    values.update(overrides)
    return CodexConversationEvent(**values)


def test_public_payload_is_allowlisted_and_requires_a_public_signal() -> None:
    payload = public_codex_event_payload(
        _event(
            event_type="item_completed",
            public_text_delta=None,
            public_message=CodexHistoryMessage(
                message_id="message-1",
                role="assistant",
                content="Resposta pública",
                timestamp=12.0,
            ),
            terminal_status=CodexTurnStatus.COMPLETED,
            metadata={
                "status": "completed",
                "nested": {"secret": True},
                "long": "x" * 600,
            },
        )
    )

    assert payload == {
        "event_schema_version": "1.0",
        "method": "item/agentMessage/delta",
        "thread_id": "thread-1",
        "turn_id": "turn-1",
        "item_id": "item-1",
        "event_type": "item_completed",
        "metadata": {"status": "completed", "long": "x" * 512},
        "public_message": {
            "message_id": "message-1",
            "role": "assistant",
            "content": "Resposta pública",
            "timestamp": 12.0,
        },
        "terminal_status": "COMPLETED",
    }
    assert (
        public_codex_event_payload(
            _event(method="item/reasoning/delta", event_type="other")
        )
        is None
    )


@pytest.mark.asyncio
async def test_relay_coalesces_deltas_and_preserves_terminal_order() -> None:
    emitted: list[dict[str, Any]] = []

    async def emit(payload: Any) -> None:
        emitted.append(dict(payload))

    relay = CodexEventRelay(emit, coalesce_seconds=0.01)
    relay.start(asyncio.get_running_loop())
    relay.submit(_event(public_text_delta="Olá"))
    relay.submit(_event(public_text_delta=", mundo"))
    relay.submit(
        _event(
            method="turn/completed",
            item_id=None,
            event_type="turn_completed",
            public_text_delta=None,
            terminal_status=CodexTurnStatus.COMPLETED,
        )
    )
    await asyncio.to_thread(relay.flush_from_thread)
    await relay.close()

    assert [item["event_type"] for item in emitted] == [
        "text_delta",
        "turn_completed",
    ]
    assert emitted[0]["public_text_delta"] == "Olá, mundo"
    assert emitted[1]["terminal_status"] == "COMPLETED"


@pytest.mark.asyncio
async def test_relay_prioritizes_terminal_event_when_backlog_is_full() -> None:
    emitted: list[dict[str, Any]] = []
    first_emit_started = asyncio.Event()
    release_first_emit = asyncio.Event()

    async def emit(payload: Any) -> None:
        if not emitted:
            first_emit_started.set()
            await release_first_emit.wait()
        emitted.append(dict(payload))

    relay = CodexEventRelay(emit, coalesce_seconds=0.0, max_backlog=1)
    relay.start(asyncio.get_running_loop())
    relay.submit(_event(public_text_delta="primeiro"))
    await first_emit_started.wait()
    relay.submit(
        _event(
            method="item/started",
            event_type="item_started",
            public_text_delta=None,
            public_action_summary="ação intermediária",
        )
    )
    relay.submit(
        _event(
            method="turn/completed",
            item_id=None,
            event_type="turn_completed",
            public_text_delta=None,
            terminal_status=CodexTurnStatus.COMPLETED,
        )
    )
    await asyncio.sleep(0)
    release_first_emit.set()
    await asyncio.to_thread(relay.flush_from_thread)
    await relay.close()

    assert [item["event_type"] for item in emitted] == [
        "text_delta",
        "turn_completed",
    ]
