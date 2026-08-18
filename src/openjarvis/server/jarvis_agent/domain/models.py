"""Immutable domain values used across HTTP, policy and adapters."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Mapping

from openjarvis.server.jarvis_agent.domain.states import ActionState, Effect


def canonical_json(value: Mapping[str, Any]) -> str:
    """Serialize one payload deterministically for approvals and idempotency."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def payload_digest(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class ToolDefinition:
    tool_id: str
    gemini_name: str
    description: str
    source: str
    provider: str
    adapter: str
    capability: str
    effect: Effect
    timeout_seconds: float
    input_schema: Mapping[str, Any] = field(default_factory=dict)

    @property
    def requires_approval(self) -> bool:
        return self.effect in {Effect.MUTATION, Effect.DELEGATION}

    def manifest_entry(self) -> dict[str, Any]:
        return {
            "name": self.gemini_name,
            "description": self.description,
            "parameters": dict(self.input_schema),
        }

    def public_entry(
        self, *, available: bool, reason: str | None = None
    ) -> dict[str, Any]:
        return {
            "id": self.tool_id,
            "name": self.gemini_name,
            "description": self.description,
            "source": self.source,
            "provider": self.provider,
            "capability": self.capability,
            "effect": self.effect.value,
            "timeout_seconds": self.timeout_seconds,
            "requires_approval": self.requires_approval,
            "available": available,
            "unavailable_reason": reason,
            "input_schema": dict(self.input_schema),
        }


@dataclass(frozen=True, slots=True)
class PreparedToolCall:
    arguments: Mapping[str, Any]
    preview: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class ExternalOperation:
    provider: str
    resource_type: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class AdapterResult:
    status: str
    summary: str
    data: Mapping[str, Any] = field(default_factory=dict)
    references: Mapping[str, str] = field(default_factory=dict)
    action_state: ActionState = ActionState.COMPLETED
    external_operation: ExternalOperation | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "summary": self.summary,
            "data": dict(self.data),
            "references": dict(self.references),
        }

    def persistence_dict(self, *, summary: str | None = None) -> dict[str, Any]:
        """Return the durable projection without external raw content."""

        return {
            "status": self.status,
            "summary": (self.summary if summary is None else summary)[:2_000],
            "references": dict(self.references),
        }
