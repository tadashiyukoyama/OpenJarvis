"""Canonical Jarvis tools backed by the AceleraChat integration contract."""

from __future__ import annotations

from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.domain.states import Effect
from openjarvis.server.jarvis_agent.registry import acelerachat_contacts
from openjarvis.server.jarvis_agent.registry.acelerachat_schemas import (
    INBOX_SELECTOR as _INBOX_SELECTOR,
)
from openjarvis.server.jarvis_agent.registry.acelerachat_schemas import (
    WHATSAPP_DESTINATION as _WHATSAPP_DESTINATION,
)
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


_ACCOUNT_INBOX_TOOLS = (
    _tool(
        "acelerachat.list_inboxes",
        "acelerachat_list_inboxes",
        "Lista todas as caixas atuais autorizadas e seus estados reais.",
        "acelerachat",
        "acelerachat_inboxes",
        "connection.inspect",
        Effect.READ,
        object_schema({}),
    ),
    _tool(
        "acelerachat.list_conversations",
        "acelerachat_list_conversations",
        "Lista conversas recentes em uma caixa ou em todas as caixas autorizadas.",
        "acelerachat",
        "acelerachat_inboxes",
        "conversations.search",
        Effect.READ,
        object_schema(
            {
                **_INBOX_SELECTOR,
                "limit": integer("Quantidade máxima.", minimum=1, maximum=25),
            }
        ),
    ),
    _tool(
        "acelerachat.read_conversation",
        "acelerachat_read_conversation",
        "Lê uma conversa de qualquer caixa autorizada por referência opaca.",
        "acelerachat",
        "acelerachat_inboxes",
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
        "acelerachat.send_message",
        "acelerachat_send_message",
        "Propõe enviar uma mensagem em qualquer conversa autorizada.",
        "acelerachat",
        "acelerachat_inboxes",
        "messages.send",
        Effect.MUTATION,
        object_schema(
            {
                "conversation_ref": string(
                    "Referência opaca da conversa.", max_length=256
                ),
                "text": string("Mensagem exata.", max_length=20_000),
            },
            ("conversation_ref", "text"),
        ),
    ),
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
                **_INBOX_SELECTOR,
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
        object_schema(
            {
                **_INBOX_SELECTOR,
                "limit": integer("Quantidade máxima.", minimum=1, maximum=25),
            }
        ),
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
    *acelerachat_contacts.acelerachat_contact_tools(),
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
                **_INBOX_SELECTOR,
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
                **_INBOX_SELECTOR,
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
        "Propõe enviar texto em uma conversa ou telefone WhatsApp pelo AceleraChat.",
        "whatsapp",
        "acelerachat_whatsapp",
        "messages.send",
        Effect.MUTATION,
        object_schema(
            {
                **_WHATSAPP_DESTINATION,
                "text": string("Mensagem exata.", max_length=4_000),
            },
            ("text",),
        ),
    ),
    _tool(
        "whatsapp.reply",
        "whatsapp_reply_message",
        "Propõe responder contextualmente a uma mensagem WhatsApp específica.",
        "whatsapp",
        "acelerachat_whatsapp",
        "messages.reply",
        Effect.MUTATION,
        object_schema(
            {
                "message_ref": string("Referência opaca da mensagem.", max_length=256),
                "text": string("Resposta exata.", max_length=4_000),
            },
            ("message_ref", "text"),
        ),
    ),
    _tool(
        "whatsapp.react",
        "whatsapp_react_message",
        "Propõe adicionar ou remover uma reação em uma mensagem WhatsApp.",
        "whatsapp",
        "acelerachat_whatsapp",
        "messages.reaction",
        Effect.MUTATION,
        object_schema(
            {
                "message_ref": string("Referência opaca da mensagem.", max_length=256),
                "reaction": string(
                    "Um emoji, ou vazio para remover.", min_length=0, max_length=64
                ),
            },
            ("message_ref", "reaction"),
        ),
    ),
    _tool(
        "whatsapp.mark_read_provider",
        "whatsapp_mark_provider_read",
        "Propõe enviar recibos de leitura pelo WhatsApp e atualizar o AceleraChat.",
        "whatsapp",
        "acelerachat_whatsapp",
        "messages.mark_read_provider",
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
    _tool(
        "whatsapp.send_media",
        "whatsapp_send_media",
        "Propõe enviar mídia de uma URL HTTPS em uma conversa ou telefone WhatsApp.",
        "whatsapp",
        "acelerachat_whatsapp",
        "messages.media_send",
        Effect.MUTATION,
        object_schema(
            {
                **_WHATSAPP_DESTINATION,
                "url": string("URL HTTPS pública da mídia.", max_length=2_048),
                "caption": string(
                    "Legenda opcional exata.", min_length=0, max_length=4_000
                ),
            },
            ("url",),
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
    return (*_ACCOUNT_INBOX_TOOLS, *_EMAIL_TOOLS, *_WHATSAPP_TOOLS)
