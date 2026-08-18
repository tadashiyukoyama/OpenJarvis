"""CLI composition helpers for the external Codex agent."""

from __future__ import annotations

from typing import Any


def build_codex_system(config: Any):
    """Build the Codex system without resolving a local inference engine."""
    from openjarvis.system import SystemBuilder

    return SystemBuilder(config).agent("codex").speech(False).build()


def run_codex_query(
    query_text: str,
    config: Any,
    *,
    context: bool,
    temperature: float,
    max_tokens: int,
    conversation_id: str,
    conversation_scope: str,
):
    """Run one Codex query with a durable CLI conversation identity."""
    from openjarvis.core.conversation_identity import ConversationIdentity

    identity = ConversationIdentity(conversation_id, conversation_scope)
    system = build_codex_system(config)
    try:
        return system.ask(
            query_text,
            context=context,
            temperature=temperature,
            max_tokens=max_tokens,
            agent="codex",
            conversation_identity=identity,
        )
    finally:
        system.close()


__all__ = ["build_codex_system", "run_codex_query"]
