from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.models import (
    AdapterResult,
    PreparedToolCall,
    ToolDefinition,
)
from openjarvis.server.jarvis_agent.domain.states import Effect
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.registry.catalog import (
    JarvisToolCatalog,
    ProviderCapabilities,
)
from openjarvis.server.jarvis_agent.services.orchestrator import (
    JarvisAgentOrchestrator,
)


class FakeAdapter:
    adapter_id = "fake"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.available = True

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]:
        capabilities = (
            frozenset({"fake.read", "fake.write", "fake.delegate"})
            if self.available
            else frozenset()
        )
        return {
            "fake_provider": ProviderCapabilities(
                "fake_provider",
                "connected" if self.available else "disconnected",
                capabilities,
                self.available,
                None if self.available else "source_disconnected",
            )
        }

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        del context
        payload = {"value": str(arguments.get("value", "")).strip()}
        return PreparedToolCall(
            payload,
            {"value": payload["value"], "risk": "fake external action"},
        )

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        del context
        payload = dict(arguments)
        self.calls.append((tool_id, payload))
        return AdapterResult(
            "completed",
            f"completed:{payload.get('value', '')}",
            {"echo": payload.get("value", "")},
        )


def fake_catalog() -> JarvisToolCatalog:
    schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    return JarvisToolCatalog(
        (
            ToolDefinition(
                "fake.read",
                "fake_read",
                "read",
                "fake",
                "fake_provider",
                "fake",
                "fake.read",
                Effect.READ,
                1.0,
                schema,
            ),
            ToolDefinition(
                "fake.write",
                "fake_write",
                "write",
                "fake",
                "fake_provider",
                "fake",
                "fake.write",
                Effect.MUTATION,
                1.0,
                schema,
            ),
            ToolDefinition(
                "fake.delegate",
                "fake_delegate",
                "delegate",
                "fake",
                "fake_provider",
                "fake",
                "fake.delegate",
                Effect.DELEGATION,
                1.0,
                schema,
            ),
        )
    )


@pytest.fixture
def agent_core(tmp_path: Path):
    adapter = FakeAdapter()
    store = JarvisAgentStore(tmp_path / "jarvis-agent.sqlite3")
    orchestrator = JarvisAgentOrchestrator(
        store=store,
        catalog=fake_catalog(),
        adapters={"fake": adapter},
    )
    yield orchestrator, adapter
    orchestrator.close()
