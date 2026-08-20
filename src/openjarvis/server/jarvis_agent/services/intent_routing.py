"""Deterministic voice-intent checks before a Gemini proposal is accepted."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import ToolDefinition

_CODEX_TARGET = r"(?:codex(?: desktop)?|cortex(?: desktop)?|agente (?:codex|cortex))"
_CODEX_DESTINATION = re.compile(rf"\b{_CODEX_TARGET}\b")
_CODEX_HISTORY = re.compile(
    r"\b(?:historico|mensagens? recentes?|ultima (?:mensagem|resposta)|"
    r"o que (?:ele|o codex) respondeu|resposta do codex)\b"
)
_CODEX_STATUS = re.compile(
    r"\b(?:status|estado|online|offline|conectado|conexao|disponivel|ocupado|"
    r"funcionando|saude)\b"
)
_CODEX_DELEGATION = re.compile(
    r"\b(?:comando|tarefa|pedido|mande|mandar|envie|enviar|encaminhe|encaminhar|"
    r"delegue|delegar|peca|pedir|solicite|solicitar|chame|chamar|acione|acionar|"
    r"contate|contatar|use|usar|fale|falar|diga|dizer|faca|fazer|rode|rodar|"
    r"execute|executar|"
    r"investigue|investigar|analise|analisar|corrija|corrigir|revise|revisar|"
    r"verifique|verificar)\b"
)
_CODEX_HANDOFF = re.compile(
    r"\b(?:mande|mandar|envie|enviar|encaminhe|encaminhar|delegue|delegar|"
    r"peca|pedir|solicite|solicitar|chame|chamar|acione|acionar|contate|"
    r"contatar|use|usar|fale|falar|diga|dizer)\b|"
    r"\bentre\s+em\s+contato\b"
)
_CODEX_WORK_ITEM = re.compile(r"\b(?:comandos?|tarefas?|pedidos?)\b")
_CODEX_DELEGATION_DESTINATION = re.compile(
    r"(?:\b(?:mande|mandar|envie|enviar|encaminhe|encaminhar|delegue|delegar|"
    r"peca|pedir|solicite|solicitar|chame|chamar|acione|acionar|contate|"
    r"contatar|use|usar|fale|falar|diga|dizer|entre\s+em\s+contato)\b"
    r".{0,120}\b(?:com o|ao|para o|pro)\s+"
    rf"{_CODEX_TARGET}\b)|"
    rf"(?:\b{_CODEX_TARGET}\b.{{0,80}}\b(?:faca|fazer|rode|rodar|"
    r"execute|executar|"
    r"investigue|investigar|analise|analisar|corrija|corrigir|revise|revisar|"
    r"verifique|verificar)\b)"
)

_WHATSAPP_SUBJECT = re.compile(r"\b(?:whatsapp|whats|zap)\b")
_WHATSAPP_SEND = re.compile(
    r"\b(?:envie|enviar|mande|mandar|responda|responder|reply)\b"
)
_WHATSAPP_SAVE_CONTACT = re.compile(
    r"(?:\b(?:salve|salvar|cadastre|cadastrar|adicione|adicionar|crie|criar)\b"
    r".{0,80}\bcontato\b)|(?:\bcontato\b.{0,80}"
    r"\b(?:salve|salvar|cadastre|cadastrar|adicione|adicionar|crie|criar)\b)"
)
_WHATSAPP_CONTACT_PHONE_CONTEXT = re.compile(
    r"\b(?:numero|telefone|celular|whatsapp|whats|zap)\b|\+[1-9]\d{5,14}"
)
_WHATSAPP_MARK_READ = re.compile(
    r"\b(?:marque|marcar)\b.{0,64}\b(?:lida|lido|leitura)\b"
)
_WHATSAPP_REACT = re.compile(r"\b(?:reaja|reagir|reacao|emoji)\b")
_WHATSAPP_READ = re.compile(
    r"\b(?:status|estado|busque|buscar|procure|procurar|consulte|consultar|"
    r"leia|ler|resuma|resumir|historico|conversa|contato)\b"
)

_EMAIL_SUBJECT = re.compile(r"\b(?:e-?mail|gmail|caixa de entrada|correio)\b")
_EMAIL_SEND = re.compile(r"\b(?:envie|enviar|mande|mandar|responda|responder|reply)\b")
_EMAIL_ARCHIVE = re.compile(r"\b(?:arquive|arquivar)\b")
_EMAIL_TRASH = re.compile(r"\b(?:lixeira|apague|apagar|exclua|excluir)\b")
_EMAIL_READ = re.compile(
    r"\b(?:busque|buscar|procure|procurar|consulte|consultar|leia|ler|"
    r"nao lidos|nao lidas|historico|conversa)\b"
)

_WHATSAPP_SEND_TOOLS = frozenset({"whatsapp.send_text", "whatsapp.reply"})
_WHATSAPP_SAVE_CONTACT_TOOLS = frozenset({"whatsapp.save_contact"})
_WHATSAPP_MARK_READ_TOOLS = frozenset(
    {"whatsapp.mark_read", "whatsapp.mark_read_internal"}
)
_WHATSAPP_REACT_TOOLS = frozenset({"whatsapp.react"})
_WHATSAPP_READ_TOOLS = frozenset(
    {
        "whatsapp.status",
        "whatsapp.search_contacts",
        "whatsapp.search_chats",
        "whatsapp.read_conversation",
        "whatsapp.summarize_conversation",
        "whatsapp.group_metadata",
        "whatsapp.privacy_read",
    }
)
_EMAIL_SEND_TOOLS = frozenset({"email.reply", "gmail.send"})
_EMAIL_ARCHIVE_TOOLS = frozenset({"email.archive", "gmail.archive"})
_EMAIL_TRASH_TOOLS = frozenset({"email.trash", "gmail.trash"})
_EMAIL_READ_TOOLS = frozenset(
    {
        "email.search",
        "email.list_unread",
        "email.read_message",
        "email.read_conversation",
        "gmail.search",
        "gmail.list_unread",
        "gmail.read_message",
        "gmail.read_thread",
    }
)


def normalize_intent(text: str) -> str:
    normalized = unicodedata.normalize("NFD", str(text))
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(normalized.casefold().split())


@dataclass(frozen=True, slots=True)
class IntentExpectation:
    source: str | None = None
    allowed_tool_ids: frozenset[str] | None = None
    explicit: bool = False


def classify_voice_intent(transcript: str) -> IntentExpectation:
    """Classify only explicit executor requests; ambiguity grants no mutation."""

    text = normalize_intent(transcript)
    if _CODEX_DESTINATION.search(text):
        # Voice recognition commonly turns "Codex" into "Cortex" and may
        # separate the hand-off verb from the canonical destination in a long
        # committed turn. A named work item plus an explicit hand-off is still
        # an unambiguous delegation and must not be downgraded by words such as
        # "funcionando" inside the task description.
        if _CODEX_DELEGATION_DESTINATION.search(text) or (
            _CODEX_HANDOFF.search(text) and _CODEX_WORK_ITEM.search(text)
        ):
            return IntentExpectation("codex", frozenset({"codex.delegate"}), True)
        # Direct status/history questions are reads even when they contain a
        # generic verb such as "verifique". This ordering prevents the exact
        # production regression that turned status checks into delegations.
        if _CODEX_HISTORY.search(text):
            return IntentExpectation("codex", frozenset({"codex.history"}), True)
        if _CODEX_STATUS.search(text):
            return IntentExpectation("codex", frozenset({"codex.status"}), True)
        if _CODEX_DELEGATION.search(text):
            return IntentExpectation("codex", frozenset({"codex.delegate"}), True)
        return IntentExpectation("codex")

    if _WHATSAPP_SAVE_CONTACT.search(text) and _WHATSAPP_CONTACT_PHONE_CONTEXT.search(
        text
    ):
        return IntentExpectation("whatsapp", _WHATSAPP_SAVE_CONTACT_TOOLS, True)

    if _WHATSAPP_SUBJECT.search(text):
        if _WHATSAPP_SAVE_CONTACT.search(text):
            return IntentExpectation("whatsapp", _WHATSAPP_SAVE_CONTACT_TOOLS, True)
        if _WHATSAPP_MARK_READ.search(text):
            return IntentExpectation("whatsapp", _WHATSAPP_MARK_READ_TOOLS, True)
        if _WHATSAPP_REACT.search(text):
            return IntentExpectation("whatsapp", _WHATSAPP_REACT_TOOLS, True)
        if _WHATSAPP_SEND.search(text):
            return IntentExpectation("whatsapp", _WHATSAPP_SEND_TOOLS, True)
        if _WHATSAPP_READ.search(text):
            return IntentExpectation("whatsapp", _WHATSAPP_READ_TOOLS, True)
        return IntentExpectation("whatsapp")

    if _EMAIL_SUBJECT.search(text):
        if _EMAIL_ARCHIVE.search(text):
            return IntentExpectation("email", _EMAIL_ARCHIVE_TOOLS, True)
        if _EMAIL_TRASH.search(text):
            return IntentExpectation("email", _EMAIL_TRASH_TOOLS, True)
        if _EMAIL_SEND.search(text):
            return IntentExpectation("email", _EMAIL_SEND_TOOLS, True)
        if _EMAIL_READ.search(text):
            return IntentExpectation("email", _EMAIL_READ_TOOLS, True)
        return IntentExpectation("email")

    return IntentExpectation()


def _canonical_source(source: str) -> str:
    return "email" if source == "gmail" else source


def validate_voice_tool_intent(tool: ToolDefinition, transcript: str) -> None:
    """Reject model-selected executors that contradict the committed turn."""

    expectation = classify_voice_intent(transcript)
    selected_source = _canonical_source(tool.source)
    if expectation.source and selected_source != expectation.source:
        raise _mismatch(
            "O executor proposto nao corresponde ao destino indicado.",
            expectation,
            tool,
        )
    if (
        expectation.allowed_tool_ids
        and tool.tool_id not in expectation.allowed_tool_ids
    ):
        raise _mismatch(
            "A ferramenta proposta nao corresponde ao pedido falado.",
            expectation,
            tool,
        )
    if tool.requires_approval and (
        not expectation.explicit or expectation.source != selected_source
    ):
        raise _mismatch(
            "A acao exige um pedido explicito para o executor correto.",
            expectation,
            tool,
        )


def _mismatch(
    message: str,
    expectation: IntentExpectation,
    tool: ToolDefinition,
) -> JarvisAgentError:
    return JarvisAgentError(
        "TOOL_INTENT_MISMATCH",
        f"{message} Nenhuma acao foi executada.",
        status_code=409,
        details={
            "expected_source": expectation.source,
            "allowed_tool_ids": sorted(expectation.allowed_tool_ids or ()),
            "selected_source": _canonical_source(tool.source),
            "selected_tool_id": tool.tool_id,
        },
    )


__all__ = [
    "IntentExpectation",
    "classify_voice_intent",
    "normalize_intent",
    "validate_voice_tool_intent",
]
