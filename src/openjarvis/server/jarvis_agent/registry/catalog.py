"""Single authoritative catalog exposed to backend, frontend and Gemini."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.domain.states import Effect
from openjarvis.server.jarvis_agent.registry.acelerachat import acelerachat_tools
from openjarvis.server.jarvis_agent.registry.codex import codex_tools
from openjarvis.server.jarvis_agent.registry.schemas import integer, object_schema


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    provider: str
    status: str
    capabilities: frozenset[str]
    connected: bool
    reason: str | None = None
    operational: bool | None = None

    @property
    def can_execute(self) -> bool:
        return self.connected if self.operational is None else self.operational

    def public_entry(self) -> dict[str, Any]:
        return {
            "id": self.provider,
            "status": self.status,
            "connected": self.connected,
            "operational": self.can_execute,
            "capabilities": sorted(self.capabilities),
            "reason": self.reason,
        }


def _operational_tool() -> ToolDefinition:
    return ToolDefinition(
        "jarvis.operational_audit",
        "jarvis_read_operational_audit",
        "Lê eventos operacionais seguros e recentes do próprio Jarvis.",
        "jarvis",
        "jarvis_local",
        "jarvis",
        "jarvis.audit",
        Effect.READ,
        5.0,
        object_schema(
            {"limit": integer("Quantidade de eventos.", minimum=1, maximum=50)}
        ),
    )


class JarvisToolCatalog:
    """Immutable definitions filtered by runtime capabilities per session."""

    def __init__(self, definitions: Iterable[ToolDefinition] | None = None) -> None:
        values = tuple(definitions or self._default_definitions())
        by_id = {item.tool_id: item for item in values}
        by_name = {item.gemini_name: item for item in values}
        if len(by_id) != len(values) or len(by_name) != len(values):
            raise ValueError("Jarvis tool IDs and Gemini aliases must be unique")
        self._definitions = values
        self._by_id = by_id
        self._by_name = by_name

    @staticmethod
    def _default_definitions() -> tuple[ToolDefinition, ...]:
        return (
            _operational_tool(),
            *acelerachat_tools(),
            *codex_tools(),
        )

    def resolve(self, identifier: str) -> ToolDefinition | None:
        return self._by_id.get(identifier) or self._by_name.get(identifier)

    @property
    def definitions(self) -> tuple[ToolDefinition, ...]:
        return self._definitions

    def snapshot(
        self,
        providers: Mapping[str, ProviderCapabilities],
        *,
        mutations_enabled: bool = True,
    ) -> dict[str, Any]:
        availability: dict[str, tuple[bool, str | None]] = {}
        public_tools: list[dict[str, Any]] = []
        manifest: list[dict[str, Any]] = []
        for tool in self._definitions:
            provider = providers.get(tool.provider)
            provider_available = bool(
                provider is not None
                and tool.capability in provider.capabilities
                and (provider.can_execute or tool.capability == "connection.inspect")
            )
            mutation_blocked = not mutations_enabled and tool.effect is not Effect.READ
            available = provider_available and not mutation_blocked
            if available:
                reason = None
            elif mutation_blocked:
                reason = "external_mutations_disabled"
            elif provider is None:
                reason = "provider_unavailable"
            elif not provider.can_execute and tool.capability != "connection.inspect":
                reason = provider.reason or "provider_not_operational"
            else:
                reason = provider.reason or "capability_unavailable"
            availability[tool.tool_id] = (available, reason)
            public_tools.append(tool.public_entry(available=available, reason=reason))
            if available:
                manifest.append(tool.manifest_entry())

        sources = self._source_entries(providers)
        canonical = json.dumps(
            {"manifest": manifest, "sources": sources},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        version = hashlib.sha256(canonical).hexdigest()
        return {
            "version": version,
            "manifest": manifest,
            "tools": public_tools,
            "sources": sources,
            "providers": [providers[key].public_entry() for key in sorted(providers)],
            "availability": availability,
        }

    @staticmethod
    def _source_entries(
        providers: Mapping[str, ProviderCapabilities],
    ) -> list[dict[str, Any]]:
        source_providers = {
            "jarvis": ("jarvis_local",),
            "email": ("acelerachat_email",),
            "whatsapp": ("acelerachat_whatsapp",),
            "codex": ("codex_desktop",),
            "hackernews": ("hackernews",),
        }
        sources: list[dict[str, Any]] = []
        for source, provider_ids in source_providers.items():
            entries = [
                providers[provider_id].public_entry()
                for provider_id in provider_ids
                if provider_id in providers
            ]
            sources.append(
                {
                    "id": source,
                    "providers": entries,
                    "manifest_enabled": source not in {"hackernews"},
                }
            )
        return sources


__all__ = ["JarvisToolCatalog", "ProviderCapabilities"]
