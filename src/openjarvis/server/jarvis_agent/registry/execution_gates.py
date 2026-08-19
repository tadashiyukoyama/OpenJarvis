"""Fail-closed runtime gates for independent external authority surfaces."""

from __future__ import annotations

import os
from dataclasses import dataclass

from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.domain.states import Effect


def _enabled(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True, slots=True)
class ToolExecutionGates:
    default_mutations: bool = True
    acelerachat_mutations: bool = True
    whatsapp_mutations: bool = True
    email_mutations: bool = True
    codex_delegation: bool = True

    @classmethod
    def uniform(cls, enabled: bool) -> "ToolExecutionGates":
        return cls(enabled, enabled, enabled, enabled, enabled)

    @classmethod
    def from_environment(cls, core_mode: str) -> "ToolExecutionGates":
        fallback = "false" if core_mode == "vps" else "true"
        default = _enabled(
            os.environ.get("OPENJARVIS_EXTERNAL_MUTATIONS_ENABLED", fallback)
        )
        return cls(
            default_mutations=default,
            acelerachat_mutations=cls._specific(
                "OPENJARVIS_ACELERACHAT_MUTATIONS_ENABLED", default
            ),
            whatsapp_mutations=cls._specific(
                "OPENJARVIS_WHATSAPP_MUTATIONS_ENABLED", default
            ),
            email_mutations=cls._specific(
                "OPENJARVIS_EMAIL_MUTATIONS_ENABLED", default
            ),
            codex_delegation=cls._specific(
                "OPENJARVIS_CODEX_DELEGATION_ENABLED", default
            ),
        )

    @staticmethod
    def _specific(name: str, default: bool) -> bool:
        value = os.environ.get(name)
        return default if value is None else _enabled(value)

    def allows(self, tool: ToolDefinition) -> bool:
        if tool.effect is Effect.READ:
            return True
        if tool.source == "acelerachat":
            return self.acelerachat_mutations
        if tool.source == "whatsapp":
            return self.whatsapp_mutations
        if tool.source == "email":
            return self.email_mutations
        if tool.source == "codex" and tool.effect is Effect.DELEGATION:
            return self.codex_delegation
        return self.default_mutations

    def blocked_reason(self, tool: ToolDefinition) -> str:
        if tool.source == "acelerachat":
            return "acelerachat_mutations_disabled"
        if tool.source == "whatsapp":
            return "whatsapp_mutations_disabled"
        if tool.source == "email":
            return "email_mutations_disabled"
        if tool.source == "codex" and tool.effect is Effect.DELEGATION:
            return "codex_delegation_disabled"
        return "external_mutations_disabled"


__all__ = ["ToolExecutionGates"]
