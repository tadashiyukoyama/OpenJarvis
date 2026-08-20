"""Bounded voice evidence used to authorize one proposed mutation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.services.intent_routing import classify_voice_intent

_VOICE_CONTEXT_SECONDS = 120.0
_VOICE_CONTEXT_TURNS = 4


@dataclass(frozen=True, slots=True)
class VoiceEvidence:
    transcript: str
    turn_ids: tuple[str, ...]


def resolve_voice_evidence(
    *,
    store: JarvisAgentStore,
    session: Mapping[str, Any],
    current_turn: Mapping[str, Any],
    tool: ToolDefinition,
) -> VoiceEvidence:
    """Resolve current speech plus, for mutations, one recent explicit anchor."""

    current_text = str(current_turn.get("transcript_text") or "").strip()
    current_id = str(current_turn["turn_id"])
    current = VoiceEvidence(current_text, (current_id,))
    if not tool.requires_approval or classify_voice_intent(current_text).explicit:
        return current

    committed_at = float(current_turn["committed_at"])
    turns = store.recent_unredacted_turns(
        session_id=str(session["session_id"]),
        generation=int(session["generation"]),
        through_turn_id=current_id,
        committed_after=committed_at - _VOICE_CONTEXT_SECONDS,
        limit=_VOICE_CONTEXT_TURNS,
    )
    anchor_index: int | None = None
    for index in range(len(turns) - 2, -1, -1):
        expectation = classify_voice_intent(str(turns[index]["transcript_text"]))
        if expectation.explicit and expectation.source:
            anchor_index = index
            break
    if anchor_index is None:
        return current

    evidence_turns = turns[anchor_index:]
    return VoiceEvidence(
        "\n".join(str(turn["transcript_text"]).strip() for turn in evidence_turns),
        tuple(str(turn["turn_id"]) for turn in evidence_turns),
    )


__all__ = ["VoiceEvidence", "resolve_voice_evidence"]
