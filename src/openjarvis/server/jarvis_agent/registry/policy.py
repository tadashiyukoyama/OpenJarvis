"""Deterministic policy checks independent from Gemini language output."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.registry.catalog import JarvisToolCatalog
from openjarvis.server.jarvis_agent.registry.validation import validate_tool_arguments


class JarvisToolPolicy:
    def __init__(self, catalog: JarvisToolCatalog) -> None:
        self._catalog = catalog

    def validate_call(
        self,
        *,
        name: str,
        arguments: Mapping[str, Any],
        session_manifest_version: str,
        current_snapshot: Mapping[str, Any],
    ) -> ToolDefinition:
        if current_snapshot.get("version") != session_manifest_version:
            raise JarvisAgentError(
                "MANIFEST_STALE",
                "As capacidades mudaram; reinicie a sessão do Jarvis.",
                status_code=409,
            )
        tool = self._catalog.resolve(name)
        if tool is None:
            raise JarvisAgentError(
                "TOOL_UNAVAILABLE",
                "A ferramenta solicitada não pertence ao catálogo Jarvis.",
                status_code=404,
            )
        availability = current_snapshot.get("availability", {}).get(tool.tool_id)
        if not availability or not availability[0]:
            raise JarvisAgentError(
                "CAPABILITY_NOT_AVAILABLE",
                "A capacidade não está disponível no provedor atual.",
                status_code=409,
                details={
                    "tool_id": tool.tool_id,
                    "reason": availability[1] if availability else None,
                },
            )
        if not isinstance(arguments, Mapping):
            raise JarvisAgentError(
                "INVALID_REQUEST", "Os argumentos da ferramenta são inválidos."
            )
        validate_tool_arguments(arguments, tool.input_schema)
        return tool
