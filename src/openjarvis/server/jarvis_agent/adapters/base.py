"""Provider-neutral adapter contract."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol

from openjarvis.server.jarvis_agent.domain.models import AdapterResult, PreparedToolCall
from openjarvis.server.jarvis_agent.registry.catalog import ProviderCapabilities


@dataclass(frozen=True, slots=True)
class AdapterContext:
    session_id: str
    project_key: str
    codex_thread_id: str
    partition_key: str
    request_id: str
    job_id: str | None = None


class JarvisAdapter(Protocol):
    adapter_id: str

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]: ...

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall: ...

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult: ...
