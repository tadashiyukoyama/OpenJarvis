"""Canonical Jarvis tools backed by the AceleraChat integration contract."""

from __future__ import annotations

from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.domain.states import Effect
from openjarvis.server.jarvis_agent.registry.schemas import (
    integer,
    object_schema,
    string,
    string_array,
)

_ADAPTER = "acelerachat"
_READ_TIMEOUT = 15.0
_WRITE_TIMEOUT = 20.0


def _tool(
    tool_id: str,
    gemini_name: str,
    description: str,
    source: str,
    provider: str,
    capability: str,
    effect: Effect,
    schema: dict,
) -> ToolDefinition:
    return ToolDefinition(
        tool_id,
        gemini_name,
        description,
        source,
        provider,
        _ADAPTER,
        capability,
        effect,
        _READ_TIMEOUT if effect is Effect.READ else _WRITE_TIMEOUT,
        schema,
    )


_EMAIL_TOOLS = (
    _tool(
        "email.search",
        "email_search_messages",
        "Busca mensagens nas caixas de e-mail de atendimento do AceleraChat.",
        "email",
        "acelerachat_email",
        "email.search",
        Effect.READ,
        object_schema(
            {
                "query": string("Texto para busca.", max_length=500),
                "limit": integer("Quantidade máxima.", minimum=1, maximum=25),
            },
            ("query",),
        ),
    ),
    _tool(
        "email.list_unread",
        "email_list_unread",
        "Lista mensagens não lidas das caixas de e-mail do AceleraChat.",
        "email",
        "acelerachat_email",
        "email.unread",
        Effect.READ,
        object_schema({"limit": integer("Quantidade máxima.", minimum=1, maximum=25)}),
    ),
    _tool(
        "email.read_message",
        "email_read_message",
        "Lê uma mensagem de e-mail por referência opaca.",
        "email",
        "acelerachat_email",
        "messages.read",
        Effect.READ,
        object_schema(
            {"message_ref": string("Referência opaca da mensagem.", max_length=256)},
            ("message_ref",),
        ),
    ),
    _tool(
        "email.read_conversation",
        "email_read_conversation",
        "Lê uma conversa de atendimento por referência opaca.",
        "email",
        "acelerachat_email",
        "email.threads",
        Effect.READ,
        object_schema(
            {
                "conversation_ref": string(
                    "Referência opaca da conversa.", max_length=256
                ),
                "limit": integer("Quantidade máxima.", minimum=1, maximum=100),
            },
            ("conversation_ref",),
        ),
    ),
    _tool(
        "email.reply",
        "email_reply_conversation",
        "Propõe responder em uma conversa de e-mail existente no AceleraChat.",
        "email",
        "acelerachat_email",
        "email.reply",
        Effect.MUTATION,
        object_schema(
            {
                "conversation_ref": string(
                    "Referência opaca da conversa.", max_length=256
                ),
                "body": string("Corpo exato da resposta.", max_length=20_000),
                "to": string_array(
                    "Destinatários opcionais.", max_items=25, item_max_length=320
                ),
                "cc": string_array(
                    "Destinatários em cópia.", max_items=25, item_max_length=320
                ),
                "bcc": string_array(
                    "Destinatários em cópia oculta.",
                    max_items=25,
                    item_max_length=320,
                ),
            },
            ("conversation_ref", "body"),
        ),
    ),
)

_WHATSAPP_TOOLS = (
    _tool(
        "whatsapp.status",
        "whatsapp_get_status",
        "Consulta o estado do WhatsApp administrado pelo AceleraChat.",
        "whatsapp",
        "acelerachat_whatsapp",
        "connection.inspect",
        Effect.READ,
        object_schema({}),
    ),
    _tool(
        "whatsapp.search_contacts",
        "whatsapp_search_contacts",
        "Busca contatos com conversas WhatsApp no AceleraChat.",
        "whatsapp",
        "acelerachat_whatsapp",
        "conversations.search",
        Effect.READ,
        object_schema(
            {
                "query": string("Nome, telefone ou texto para busca.", max_length=160),
                "limit": integer("Quantidade máxima.", minimum=1, maximum=25),
            },
            ("query",),
        ),
    ),
    _tool(
        "whatsapp.search_chats",
        "whatsapp_search_chats",
        "Busca conversas WhatsApp no AceleraChat.",
        "whatsapp",
        "acelerachat_whatsapp",
        "conversations.search",
        Effect.READ,
        object_schema(
            {
                "query": string("Nome do contato para busca.", max_length=160),
                "limit": integer("Quantidade máxima.", minimum=1, maximum=25),
            }
        ),
    ),
    _tool(
        "whatsapp.read_conversation",
        "whatsapp_read_conversation",
        "Lê um histórico limitado de conversa WhatsApp por referência opaca.",
        "whatsapp",
        "acelerachat_whatsapp",
        "messages.read",
        Effect.READ,
        object_schema(
            {
                "conversation_ref": string(
                    "Referência opaca da conversa.", max_length=256
                ),
                "limit": integer("Quantidade máxima.", minimum=1, maximum=100),
            },
            ("conversation_ref",),
        ),
    ),
    _tool(
        "whatsapp.summarize_conversation",
        "whatsapp_summarize_conversation",
        "Obtém contexto limitado para resumir uma conversa WhatsApp.",
        "whatsapp",
        "acelerachat_whatsapp",
        "messages.read",
        Effect.READ,
        object_schema(
            {
                "conversation_ref": string(
                    "Referência opaca da conversa.", max_length=256
                ),
                "limit": integer("Quantidade máxima.", minimum=1, maximum=100),
            },
            ("conversation_ref",),
        ),
    ),
    _tool(
        "whatsapp.send_text",
        "whatsapp_send_text",
        "Propõe enviar texto em uma conversa WhatsApp existente no AceleraChat.",
        "whatsapp",
        "acelerachat_whatsapp",
        "messages.send",
        Effect.MUTATION,
        object_schema(
            {
                "contact_name": string("Nome exato do contato.", max_length=240),
                "conversation_ref": string(
                    "Referência opaca opcional da conversa.", max_length=256
                ),
                "text": string("Mensagem exata.", max_length=4_000),
            },
            ("text",),
        ),
    ),
    _tool(
        "whatsapp.mark_read_internal",
        "whatsapp_mark_acelerachat_read",
        "Propõe marcar a conversa como lida apenas dentro do AceleraChat.",
        "whatsapp",
        "acelerachat_whatsapp",
        "messages.mark_read_internal",
        Effect.MUTATION,
        object_schema(
            {
                "conversation_ref": string(
                    "Referência opaca da conversa.", max_length=256
                )
            },
            ("conversation_ref",),
        ),
    ),
)


def acelerachat_tools() -> tuple[ToolDefinition, ...]:
    return (*_EMAIL_TOOLS, *_WHATSAPP_TOOLS)
