from __future__ import annotations

from typing import Any

import pytest

from openjarvis.server.jarvis_agent.adapters.acelerachat.capabilities import (
    AceleraChatCapabilities,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.config import AceleraChatConfig
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError


def _inbox(
    inbox_id: int,
    *,
    supports_send: bool,
    connected: bool = True,
) -> dict[str, Any]:
    return {
        "id": inbox_id,
        "name": f"Caixa {inbox_id}",
        "channel_type": "Channel::Whatsapp",
        "inbox_type": "Whatsapp",
        "connection": {
            "state": "connected" if connected else "disconnected",
            "connected": connected,
            "operational": connected,
            "provider": "evolution",
        },
        "capabilities": {
            "messages.read": {"supported": True},
            "messages.send": {"supported": supports_send},
        },
    }


class InboxClient:
    def __init__(self, inboxes: list[dict[str, Any]]) -> None:
        self._inboxes = inboxes

    def list_inboxes(self) -> list[dict[str, Any]]:
        return self._inboxes


def _capabilities(
    inboxes: list[dict[str, Any]], *, preferred_id: int | None = None
) -> AceleraChatCapabilities:
    config = AceleraChatConfig(
        bearer_token="test-token",
        whatsapp_inbox_id=preferred_id,
    )
    return AceleraChatCapabilities(config, InboxClient(inboxes))  # type: ignore[arg-type]


def test_explicit_inbox_without_capability_is_not_reported_as_disconnected() -> None:
    capabilities = _capabilities([_inbox(20, supports_send=False)])

    with pytest.raises(JarvisAgentError) as raised:
        capabilities.select(
            "acelerachat_whatsapp",
            inbox_id=20,
            required_capability="messages.send",
        )

    assert raised.value.code == "CAPABILITY_NOT_AVAILABLE"


def test_preferred_inbox_cannot_bypass_required_capability() -> None:
    capabilities = _capabilities(
        [
            _inbox(20, supports_send=False),
            _inbox(21, supports_send=True),
        ],
        preferred_id=20,
    )

    selected = capabilities.select(
        "acelerachat_whatsapp",
        required_capability="messages.send",
    )

    assert selected.inbox is not None
    assert selected.inbox.id == 21


def test_disconnected_inbox_remains_a_connection_error() -> None:
    capabilities = _capabilities([_inbox(20, supports_send=True, connected=False)])

    with pytest.raises(JarvisAgentError) as raised:
        capabilities.select(
            "acelerachat_whatsapp",
            inbox_id=20,
            required_capability="messages.send",
        )

    assert raised.value.code == "SOURCE_DISCONNECTED"
