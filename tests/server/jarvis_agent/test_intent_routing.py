from __future__ import annotations

import sqlite3
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
from openjarvis.server.jarvis_agent.registry.codex import codex_tools
from openjarvis.server.jarvis_agent.services.intent_routing import (
    classify_voice_intent,
    validate_voice_tool_intent,
)
from openjarvis.server.jarvis_agent.services.orchestrator import (
    JarvisAgentOrchestrator,
)


class CodexProbeAdapter:
    adapter_id = "codex"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def provider_capabilities(self) -> Mapping[str, ProviderCapabilities]:
        return {
            "codex_desktop": ProviderCapabilities(
                "codex_desktop",
                "connected",
                frozenset({"codex.status", "codex.history", "codex.delegate"}),
                True,
            )
        }

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        del context
        return PreparedToolCall(dict(arguments), {"tool_id": tool_id})

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        del context
        self.calls.append((tool_id, dict(arguments)))
        return AdapterResult("completed", f"{tool_id} concluido")


@pytest.fixture
def codex_core(tmp_path: Path):
    adapter = CodexProbeAdapter()
    orchestrator = JarvisAgentOrchestrator(
        store=JarvisAgentStore(tmp_path / "intent.sqlite3"),
        catalog=JarvisToolCatalog(codex_tools()),
        adapters={"codex": adapter},
        mutations_enabled=True,
    )
    yield orchestrator, adapter
    orchestrator.close()


def _session(orchestrator: JarvisAgentOrchestrator) -> dict[str, Any]:
    return orchestrator.create_session(
        project_key="D:/dev/project", codex_thread_id="thread-1"
    )


def _commit(
    orchestrator: JarvisAgentOrchestrator,
    session: Mapping[str, Any],
    transcript: str,
    turn_id: str = "turn-1",
) -> None:
    orchestrator.commit_turn(
        session_id=str(session["session_id"]),
        generation=int(session["generation"]),
        turn_id=turn_id,
        transcript=transcript,
    )


def test_codex_delegation_cannot_be_replaced_by_status(codex_core) -> None:
    orchestrator, adapter = codex_core
    session = _session(orchestrator)
    _commit(orchestrator, session, "Mande um comando de teste para o Codex.")

    with pytest.raises(JarvisAgentError) as error:
        orchestrator.propose(
            session_id=session["session_id"],
            generation=session["generation"],
            function_call_id="wrong-status",
            tool_name="codex_get_status",
            arguments={},
            turn_id="turn-1",
        )

    assert error.value.code == "TOOL_INTENT_MISMATCH"
    assert adapter.calls == []
    assert orchestrator.store.get_turn("turn-1")["transcript_text"] is not None
    rejected = [
        event
        for event in orchestrator.events.after(0, 100)
        if event["event_type"] == "tool_call_rejected"
    ]
    assert rejected[0]["payload"] == {
        "code": "TOOL_INTENT_MISMATCH",
        "requested_name": "codex_get_status",
        "tool_id": "codex.status",
    }
    with sqlite3.connect(orchestrator.store.path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM jarvis_actions").fetchone()[0] == 0
        )


def test_explicit_codex_delegation_reaches_visual_approval(codex_core) -> None:
    orchestrator, adapter = codex_core
    session = _session(orchestrator)
    _commit(orchestrator, session, "Peça ao Codex para executar um teste controlado.")

    result = orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id="correct-delegate",
        tool_name="codex_delegate_task",
        arguments={"command": "Execute um teste controlado sem mutacoes externas."},
        turn_id="turn-1",
    )

    assert result["tool_id"] == "codex.delegate"
    assert result["status"] == "approval_required"
    assert adapter.calls == []
    assert orchestrator.store.get_turn("turn-1")["transcript_text"] is None


def test_long_asr_codex_delegation_reaches_visual_approval(codex_core) -> None:
    orchestrator, adapter = codex_core
    session = _session(orchestrator)
    _commit(
        orchestrator,
        session,
        (
            "Preciso que voce mande um comando pro pro Cortex pra gente poder testar "
            "se ta funcionando a ponte entre o OpenJarvis e o Codex. O comando e o "
            "seguinte: teste 03 responda somente OK."
        ),
    )

    result = orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id="asr-delegate",
        tool_name="codex_delegate_task",
        arguments={"command": "Teste 03. Responda somente OK."},
        turn_id="turn-1",
    )

    assert result["tool_id"] == "codex.delegate"
    assert result["status"] == "approval_required"
    assert adapter.calls == []
    assert orchestrator.store.get_turn("turn-1")["transcript_text"] is None


def test_codex_status_question_remains_a_read(codex_core) -> None:
    orchestrator, adapter = codex_core
    session = _session(orchestrator)
    _commit(orchestrator, session, "Verifique se o Codex está conectado e disponível.")

    result = orchestrator.propose(
        session_id=session["session_id"],
        generation=session["generation"],
        function_call_id="status-read",
        tool_name="codex_get_status",
        arguments={},
        turn_id="turn-1",
    )

    assert result["status"] == "completed"
    assert adapter.calls == [("codex.status", {})]


def test_exact_retry_returns_existing_action_after_turn_redaction(codex_core) -> None:
    orchestrator, adapter = codex_core
    session = _session(orchestrator)
    _commit(orchestrator, session, "Verifique se o Codex está conectado.")
    request = {
        "session_id": session["session_id"],
        "generation": session["generation"],
        "function_call_id": "status-retry",
        "tool_name": "codex_get_status",
        "arguments": {},
        "turn_id": "turn-1",
    }

    first = orchestrator.propose(**request)
    repeated = orchestrator.propose(**request)

    assert repeated["action_id"] == first["action_id"]
    assert repeated["tool_id"] == first["tool_id"]
    assert repeated["status"] == "completed"
    assert adapter.calls == [("codex.status", {})]
    assert orchestrator.store.get_turn("turn-1")["transcript_text"] is None
    assert [event["event_type"] for event in orchestrator.events.after(0, 100)].count(
        "duplicate_action"
    ) == 1


def test_turn_from_another_session_is_rejected(codex_core) -> None:
    orchestrator, _ = codex_core
    first = _session(orchestrator)
    second = _session(orchestrator)
    _commit(orchestrator, first, "Qual é o status do Codex?", "foreign-turn")

    with pytest.raises(JarvisAgentError) as error:
        orchestrator.propose(
            session_id=second["session_id"],
            generation=second["generation"],
            function_call_id="foreign",
            tool_name="codex_get_status",
            arguments={},
            turn_id="foreign-turn",
        )

    assert error.value.code == "INVALID_REQUEST"


def test_classifier_distinguishes_mutating_source_actions() -> None:
    send = classify_voice_intent("Envie uma mensagem pelo WhatsApp para Maria")
    save_contact = classify_voice_intent(
        "Salve o contato Maria com o número +5511999999999"
    )
    mark_read = classify_voice_intent("Marque a conversa do WhatsApp como lida")
    email = classify_voice_intent("Responda o e-mail do cliente")

    assert send.allowed_tool_ids == frozenset({"whatsapp.send_text", "whatsapp.reply"})
    assert save_contact.source == "whatsapp"
    assert save_contact.allowed_tool_ids == frozenset({"whatsapp.save_contact"})
    assert save_contact.explicit is True
    assert mark_read.allowed_tool_ids == frozenset(
        {"whatsapp.mark_read", "whatsapp.mark_read_internal"}
    )
    assert email.allowed_tool_ids == frozenset({"email.reply", "gmail.send"})


def test_contact_save_and_message_send_cannot_authorize_each_other() -> None:
    definitions = {tool.tool_id: tool for tool in JarvisToolCatalog().definitions}

    with pytest.raises(JarvisAgentError) as save_error:
        validate_voice_tool_intent(
            definitions["whatsapp.save_contact"],
            "Envie uma mensagem pelo WhatsApp para Maria.",
        )
    with pytest.raises(JarvisAgentError) as send_error:
        validate_voice_tool_intent(
            definitions["whatsapp.send_text"],
            "Cadastre o contato do WhatsApp de Maria.",
        )

    assert save_error.value.code == "TOOL_INTENT_MISMATCH"
    assert send_error.value.code == "TOOL_INTENT_MISMATCH"


def test_explicit_codex_destination_wins_over_whatsapp_subject() -> None:
    intent = classify_voice_intent(
        "Peça ao Codex para verificar o status do WhatsApp e encontrar a causa."
    )

    assert intent.source == "codex"
    assert intent.allowed_tool_ids == frozenset({"codex.delegate"})


@pytest.mark.parametrize(
    "transcript",
    [
        "Entre em contato com o Codex para executar um teste.",
        "Quero que o Codex faça uma auditoria deste problema.",
        "Acione o agente Codex e mande esta tarefa.",
    ],
)
def test_common_spoken_codex_delegation_phrases_are_deterministic(
    transcript: str,
) -> None:
    intent = classify_voice_intent(transcript)

    assert intent.source == "codex"
    assert intent.allowed_tool_ids == frozenset({"codex.delegate"})
    assert intent.explicit is True


@pytest.mark.parametrize(
    "transcript",
    [
        "Mande um comando para o Cortex: teste 03, responda somente OK.",
        (
            "Mande uma tarefa para o Cortex. Depois confirme se esta funcionando a "
            "ponte entre o OpenJarvis e o Codex."
        ),
    ],
)
def test_codex_asr_alias_and_status_words_preserve_delegation(
    transcript: str,
) -> None:
    intent = classify_voice_intent(transcript)

    assert intent.source == "codex"
    assert intent.allowed_tool_ids == frozenset({"codex.delegate"})
    assert intent.explicit is True


@pytest.mark.parametrize(
    "transcript",
    [
        "Verifique se o Codex esta funcionando.",
        "Me mande o status do Codex.",
    ],
)
def test_codex_status_requests_are_not_promoted_to_delegation(
    transcript: str,
) -> None:
    intent = classify_voice_intent(transcript)

    assert intent.source == "codex"
    assert intent.allowed_tool_ids == frozenset({"codex.status"})
    assert intent.explicit is True


def test_mutation_without_explicit_source_is_rejected() -> None:
    tool = ToolDefinition(
        "whatsapp.send_text",
        "whatsapp_send_text",
        "send",
        "whatsapp",
        "provider",
        "adapter",
        "whatsapp.send",
        Effect.MUTATION,
        10.0,
        {},
    )

    with pytest.raises(JarvisAgentError) as error:
        validate_voice_tool_intent(tool, "Mande uma mensagem para Maria")

    assert error.value.code == "TOOL_INTENT_MISMATCH"
