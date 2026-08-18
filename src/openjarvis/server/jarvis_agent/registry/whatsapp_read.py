"""Read-only WhatsApp tool definitions."""

from __future__ import annotations

from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.domain.states import Effect
from openjarvis.server.jarvis_agent.registry.schemas import (
    integer,
    object_schema,
    string,
)

_COMMON = ("whatsapp", "whatsapp_baileys", "whatsapp", Effect.READ, 10.0)
_QUERY_LIMIT = object_schema(
    {
        "query": string("Nome ou texto para busca.", max_length=160),
        "limit": integer("Limite de resultados.", minimum=1, maximum=100),
    }
)
_CONVERSATION = object_schema(
    {
        "chat_ref": string("Referência opaca da conversa.", max_length=160),
        "query": string("Texto opcional dentro da conversa.", max_length=160),
        "limit": integer("Limite de mensagens.", minimum=1, maximum=200),
    },
    ("chat_ref",),
)

_WHATSAPP_READ_TOOLS = (
    ToolDefinition(
        "whatsapp.status",
        "whatsapp_get_status",
        "Consulta o estado real do provedor WhatsApp Baileys.",
        *_COMMON[:3],
        "whatsapp.status",
        *_COMMON[3:],
        object_schema({}),
    ),
    ToolDefinition(
        "whatsapp.search_contacts",
        "whatsapp_search_contacts",
        "Busca contatos WhatsApp por nome sem revelar identificadores internos.",
        *_COMMON[:3],
        "whatsapp.contacts",
        *_COMMON[3:],
        _QUERY_LIMIT,
    ),
    ToolDefinition(
        "whatsapp.search_chats",
        "whatsapp_search_chats",
        "Busca conversas WhatsApp no índice local.",
        *_COMMON[:3],
        "whatsapp.chats",
        *_COMMON[3:],
        _QUERY_LIMIT,
    ),
    ToolDefinition(
        "whatsapp.read_conversation",
        "whatsapp_read_conversation",
        "Lê um histórico limitado usando uma referência opaca de conversa.",
        *_COMMON[:3],
        "whatsapp.messages",
        *_COMMON[3:],
        _CONVERSATION,
    ),
    ToolDefinition(
        "whatsapp.summarize_conversation",
        "whatsapp_summarize_conversation",
        "Obtém contexto limitado para resumir uma conversa WhatsApp.",
        *_COMMON[:3],
        "whatsapp.summary",
        *_COMMON[3:],
        object_schema(
            {
                "chat_ref": string("Referência opaca da conversa.", max_length=160),
                "limit": integer("Limite de mensagens.", minimum=1, maximum=200),
            },
            ("chat_ref",),
        ),
    ),
    ToolDefinition(
        "whatsapp.group_metadata",
        "whatsapp_get_group_metadata",
        "Consulta metadados limitados de um grupo WhatsApp.",
        *_COMMON[:3],
        "whatsapp.group_metadata",
        *_COMMON[3:],
        object_schema(
            {"chat_ref": string("Referência opaca do grupo.", max_length=160)},
            ("chat_ref",),
        ),
    ),
    ToolDefinition(
        "whatsapp.privacy_read",
        "whatsapp_read_privacy",
        "Consulta as configurações públicas de privacidade do WhatsApp.",
        *_COMMON[:3],
        "whatsapp.privacy_read",
        *_COMMON[3:],
        object_schema({}),
    ),
)


def whatsapp_read_tools() -> tuple[ToolDefinition, ...]:
    return _WHATSAPP_READ_TOOLS
