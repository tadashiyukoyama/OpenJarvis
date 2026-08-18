"""Read-only adapter for the sanitized local Jarvis operational ledger."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import AdapterResult, PreparedToolCall
from openjarvis.server.jarvis_agent.registry.catalog import ProviderCapabilities


class OperationalAdapter:
    adapter_id = "jarvis"

    def __init__(self, store_getter: Callable[[], Any | None]) -> None:
        self._store_getter = store_getter

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]:
        return {
            "jarvis_local": ProviderCapabilities(
                "jarvis_local",
                "available",
                frozenset({"jarvis.audit"}),
                True,
            )
        }

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        del tool_id, context
        limit = min(50, max(1, int(arguments.get("limit", 20))))
        return PreparedToolCall({"limit": limit}, {})

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        if tool_id != "jarvis.operational_audit":
            raise JarvisAgentError(
                "TOOL_UNAVAILABLE", "Ferramenta Jarvis desconhecida."
            )
        store = self._store_getter()
        if store is None or not context.codex_thread_id:
            return AdapterResult(
                "completed",
                "Não há eventos operacionais para esta conversa.",
                {"events": []},
            )
        events = store.list(
            context.codex_thread_id,
            limit=min(50, max(1, int(arguments.get("limit", 20)))),
        )
        return AdapterResult(
            "completed",
            "Eventos operacionais carregados.",
            {
                "events": [
                    {
                        "event_type": event.event_type,
                        "text": event.text,
                        "occurred_at": event.occurred_at,
                    }
                    for event in events
                ]
            },
        )
