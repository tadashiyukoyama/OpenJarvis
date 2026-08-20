from __future__ import annotations

import sqlite3
import time
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
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


def _tool(
    tool_id: str,
    gemini_name: str,
    source: str,
    capability: str,
) -> ToolDefinition:
    return ToolDefinition(
        tool_id,
        gemini_name,
        "Propoe uma mutacao controlada.",
        source,
        "voice_probe",
        "voice_probe",
        capability,
        Effect.MUTATION if source == "whatsapp" else Effect.DELEGATION,
        10.0,
        {
            "type": "object",
            "properties": {
                "contact_name": {"type": "string"},
                "text": {"type": "string"},
                "command": {"type": "string"},
            },
            "additionalProperties": False,
        },
    )


class VoiceProbeAdapter:
    adapter_id = "voice_probe"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]:
        return {
            "voice_probe": ProviderCapabilities(
                "voice_probe",
                "connected",
                frozenset({"whatsapp.send", "codex.delegate"}),
                True,
            )
        }

    def prepare(
        self,
        tool_id: str,
        arguments: Mapping[str, Any],
        context: AdapterContext,
    ) -> PreparedToolCall:
        del context
        return PreparedToolCall(dict(arguments), {"tool_id": tool_id})

    def execute(
        self,
        tool_id: str,
        arguments: Mapping[str, Any],
        context: AdapterContext,
    ) -> AdapterResult:
        del context
        self.calls.append((tool_id, dict(arguments)))
        return AdapterResult("completed", "Executado.")


@pytest.fixture
def voice_core(tmp_path: Path):
    adapter = VoiceProbeAdapter()
    catalog = JarvisToolCatalog(
        (
            _tool(
                "whatsapp.send_text",
                "whatsapp_send_text",
                "whatsapp",
                "whatsapp.send",
            ),
            _tool("codex.delegate", "codex_delegate_task", "codex", "codex.delegate"),
        )
    )
    orchestrator = JarvisAgentOrchestrator(
        store=JarvisAgentStore(tmp_path / "voice-evidence.sqlite3"),
        catalog=catalog,
        adapters={"voice_probe": adapter},
    )
    yield orchestrator, adapter
    orchestrator.close()


def _session(orchestrator: JarvisAgentOrchestrator) -> dict[str, Any]:
    return orchestrator.create_session(project_key="D:/dev/project")


def _commit(
    orchestrator: JarvisAgentOrchestrator,
    session: Mapping[str, Any],
    transcript: str,
    turn_id: str,
) -> None:
    orchestrator.commit_turn(
        session_id=str(session["session_id"]),
        generation=int(session["generation"]),
        turn_id=turn_id,
        transcript=transcript,
    )


def _send_request(
    session: Mapping[str, Any], turn_id: str, call_id: str
) -> dict[str, Any]:
    return {
        "session_id": session["session_id"],
        "generation": session["generation"],
        "function_call_id": call_id,
        "tool_name": "whatsapp_send_text",
        "arguments": {
            "contact_name": "Klaus Consultor",
            "text": "Teste controlado.",
        },
        "turn_id": turn_id,
    }


def test_split_whatsapp_intent_reaches_one_visual_approval(voice_core) -> None:
    orchestrator, adapter = voice_core
    session = _session(orchestrator)
    _commit(
        orchestrator,
        session,
        "Quero que voce mande uma mensagem pelo WhatsApp.",
        "turn-whatsapp-intent",
    )
    _commit(
        orchestrator,
        session,
        "Para Klaus Consultor: teste controlado.",
        "turn-whatsapp-details",
    )

    request = _send_request(session, "turn-whatsapp-details", "split-whatsapp-send")
    pending = orchestrator.propose(**request)
    repeated = orchestrator.propose(**request)

    assert pending["status"] == "approval_required"
    assert repeated["action_id"] == pending["action_id"]
    assert adapter.calls == []
    assert (
        orchestrator.store.get_turn("turn-whatsapp-intent")["transcript_text"] is None
    )
    assert (
        orchestrator.store.get_turn("turn-whatsapp-details")["transcript_text"] is None
    )


def test_split_mutation_without_recent_explicit_source_is_rejected(voice_core) -> None:
    orchestrator, adapter = voice_core
    session = _session(orchestrator)
    _commit(
        orchestrator,
        session,
        "Para Klaus Consultor: teste controlado.",
        "turn-no-source",
    )

    with pytest.raises(JarvisAgentError) as error:
        orchestrator.propose(**_send_request(session, "turn-no-source", "no-source"))

    assert error.value.code == "TOOL_INTENT_MISMATCH"
    assert adapter.calls == []
    assert orchestrator.store.get_turn("turn-no-source")["transcript_text"] is not None


def test_expired_voice_anchor_does_not_authorize_a_mutation(voice_core) -> None:
    orchestrator, adapter = voice_core
    session = _session(orchestrator)
    _commit(
        orchestrator,
        session,
        "Mande uma mensagem pelo WhatsApp.",
        "turn-expired-anchor",
    )
    with sqlite3.connect(orchestrator.store.path) as connection:
        connection.execute(
            "UPDATE jarvis_turns SET committed_at = ? WHERE turn_id = ?",
            (time.time() - 121, "turn-expired-anchor"),
        )
    _commit(
        orchestrator,
        session,
        "Para Klaus Consultor: teste controlado.",
        "turn-after-expiry",
    )

    with pytest.raises(JarvisAgentError) as error:
        orchestrator.propose(
            **_send_request(session, "turn-after-expiry", "expired-anchor")
        )

    assert error.value.code == "TOOL_INTENT_MISMATCH"
    assert adapter.calls == []


def test_voice_anchor_older_than_four_turns_is_not_used(voice_core) -> None:
    orchestrator, adapter = voice_core
    session = _session(orchestrator)
    _commit(
        orchestrator,
        session,
        "Mande uma mensagem pelo WhatsApp.",
        "turn-outside-limit",
    )
    for index in range(3):
        _commit(
            orchestrator,
            session,
            f"Detalhe intermediario {index}.",
            f"turn-mid-{index}",
        )
    _commit(orchestrator, session, "Para Klaus: teste.", "turn-after-limit")

    with pytest.raises(JarvisAgentError) as error:
        orchestrator.propose(
            **_send_request(session, "turn-after-limit", "outside-turn-limit")
        )

    assert error.value.code == "TOOL_INTENT_MISMATCH"
    assert adapter.calls == []


def test_most_recent_explicit_executor_wins_over_an_older_anchor(voice_core) -> None:
    orchestrator, adapter = voice_core
    session = _session(orchestrator)
    _commit(
        orchestrator,
        session,
        "Mande uma mensagem pelo WhatsApp.",
        "turn-old-whatsapp",
    )
    _commit(
        orchestrator,
        session,
        "Peca ao Codex para executar o proximo teste.",
        "turn-recent-codex",
    )
    _commit(
        orchestrator,
        session,
        "Para Klaus Consultor: teste controlado.",
        "turn-final-details",
    )

    with pytest.raises(JarvisAgentError) as error:
        orchestrator.propose(
            **_send_request(session, "turn-final-details", "wrong-old-anchor")
        )

    assert error.value.code == "TOOL_INTENT_MISMATCH"
    assert error.value.details["expected_source"] == "codex"
    assert adapter.calls == []


def test_whatsapp_read_intent_cannot_authorize_a_send(voice_core) -> None:
    orchestrator, adapter = voice_core
    session = _session(orchestrator)
    _commit(
        orchestrator,
        session,
        "Leia a conversa do WhatsApp com Klaus.",
        "turn-read-only",
    )

    with pytest.raises(JarvisAgentError) as error:
        orchestrator.propose(
            **_send_request(session, "turn-read-only", "read-cannot-send")
        )

    assert error.value.code == "TOOL_INTENT_MISMATCH"
    assert adapter.calls == []
