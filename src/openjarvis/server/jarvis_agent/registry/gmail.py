"""Canonical Gmail tool definitions."""

from __future__ import annotations

from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.domain.states import Effect
from openjarvis.server.jarvis_agent.registry.schemas import (
    integer,
    object_schema,
    string,
)

_READ_TIMEOUT = 15.0
_MUTATION_TIMEOUT = 20.0

_GMAIL_TOOLS = (
    ToolDefinition(
        "gmail.search",
        "gmail_search_emails",
        "Busca e-mails no Gmail conectado com uma consulta limitada.",
        "gmail",
        "gmail",
        "gmail",
        "gmail.search",
        Effect.READ,
        _READ_TIMEOUT,
        object_schema(
            {
                "query": string("Consulta de busca do Gmail.", max_length=500),
                "max_results": integer(
                    "Quantidade máxima de resultados.", minimum=1, maximum=25
                ),
            },
            ("query",),
        ),
    ),
    ToolDefinition(
        "gmail.list_unread",
        "gmail_list_unread",
        "Lista e-mails não lidos do Gmail conectado.",
        "gmail",
        "gmail",
        "gmail",
        "gmail.search",
        Effect.READ,
        _READ_TIMEOUT,
        object_schema(
            {
                "max_results": integer(
                    "Quantidade máxima de resultados.", minimum=1, maximum=25
                )
            }
        ),
    ),
    ToolDefinition(
        "gmail.read_message",
        "gmail_read_email",
        "Lê um e-mail por sua referência opaca.",
        "gmail",
        "gmail",
        "gmail",
        "gmail.read",
        Effect.READ,
        _READ_TIMEOUT,
        object_schema(
            {"message_ref": string("Referência opaca do e-mail.", max_length=256)},
            ("message_ref",),
        ),
    ),
    ToolDefinition(
        "gmail.read_thread",
        "gmail_read_thread",
        "Lê uma conversa do Gmail usando uma referência opaca.",
        "gmail",
        "gmail",
        "gmail",
        "gmail.thread",
        Effect.READ,
        _READ_TIMEOUT,
        object_schema(
            {"thread_ref": string("Referência opaca da conversa.", max_length=256)},
            ("thread_ref",),
        ),
    ),
    ToolDefinition(
        "gmail.send",
        "gmail_send_email",
        "Propõe o envio de um e-mail de texto simples.",
        "gmail",
        "gmail_oauth",
        "gmail",
        "gmail.send",
        Effect.MUTATION,
        _MUTATION_TIMEOUT,
        object_schema(
            {
                "to": string("Destinatário.", max_length=320),
                "subject": string("Assunto.", max_length=998),
                "body": string("Corpo do e-mail.", max_length=20000),
                "cc": string("Destinatários em cópia.", max_length=2000),
            },
            ("to", "body"),
        ),
    ),
    ToolDefinition(
        "gmail.archive",
        "gmail_archive_email",
        "Propõe arquivar um e-mail identificado por referência opaca.",
        "gmail",
        "gmail_oauth",
        "gmail",
        "gmail.archive",
        Effect.MUTATION,
        _MUTATION_TIMEOUT,
        object_schema(
            {"message_ref": string("Referência opaca do e-mail.", max_length=256)},
            ("message_ref",),
        ),
    ),
    ToolDefinition(
        "gmail.trash",
        "gmail_trash_email",
        "Propõe mover um e-mail para a lixeira.",
        "gmail",
        "gmail_oauth",
        "gmail",
        "gmail.trash",
        Effect.MUTATION,
        _MUTATION_TIMEOUT,
        object_schema(
            {"message_ref": string("Referência opaca do e-mail.", max_length=256)},
            ("message_ref",),
        ),
    ),
)


def gmail_tools() -> tuple[ToolDefinition, ...]:
    return _GMAIL_TOOLS
