"""Canonical Codex Desktop tool definitions."""

from __future__ import annotations

from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.domain.states import Effect
from openjarvis.server.jarvis_agent.registry.schemas import (
    integer,
    object_schema,
    string,
)


def codex_tools() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            "codex.status",
            "codex_get_status",
            "Consulta disponibilidade do Codex e da conversa selecionada.",
            "codex",
            "codex_desktop",
            "codex",
            "codex.status",
            Effect.READ,
            5.0,
            object_schema({}),
        ),
        ToolDefinition(
            "codex.history",
            "codex_read_recent_history",
            "Lê o histórico público recente da conversa Codex selecionada.",
            "codex",
            "codex_desktop",
            "codex",
            "codex.history",
            Effect.READ,
            7.0,
            object_schema(
                {
                    "limit": integer(
                        "Quantidade máxima de mensagens recentes.",
                        minimum=1,
                        maximum=30,
                    )
                }
            ),
        ),
        ToolDefinition(
            "codex.delegate",
            "codex_delegate_task",
            (
                "Propõe uma tarefa exata ao Codex Desktop no projeto "
                "e conversa escolhidos."
            ),
            "codex",
            "codex_desktop",
            "codex",
            "codex.delegate",
            Effect.DELEGATION,
            300.0,
            object_schema(
                {
                    "command": string(
                        "Comando completo e exato a ser delegado.", max_length=20000
                    ),
                },
                ("command",),
            ),
        ),
    )
