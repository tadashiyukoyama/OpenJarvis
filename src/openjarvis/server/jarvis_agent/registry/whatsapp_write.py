"""Mutating WhatsApp tool definitions; every one requires visual approval."""

from __future__ import annotations

from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.domain.states import Effect
from openjarvis.server.jarvis_agent.registry.schemas import (
    boolean,
    integer,
    object_schema,
    string,
    string_array,
)

_BASE = ("whatsapp", "whatsapp_baileys", "whatsapp", Effect.MUTATION, 20.0)


def _tool(
    tool_id: str,
    name: str,
    description: str,
    capability: str,
    schema: dict,
) -> ToolDefinition:
    return ToolDefinition(
        tool_id, name, description, *_BASE[:3], capability, *_BASE[3:], schema
    )


_DESTINATION = {
    "contact_name": string("Nome do contato a resolver.", max_length=240),
    "chat_ref": string("Referência opaca opcional da conversa.", max_length=160),
}

_MESSAGE_TOOLS = (
    _tool(
        "whatsapp.send_text",
        "whatsapp_send_text",
        "Propõe enviar texto para um contato ou conversa WhatsApp.",
        "whatsapp.send",
        object_schema(
            {**_DESTINATION, "text": string("Mensagem exata.", max_length=4000)},
            ("text",),
        ),
    ),
    _tool(
        "whatsapp.reply",
        "whatsapp_reply_message",
        "Propõe responder a uma mensagem por sua referência opaca.",
        "whatsapp.reply",
        object_schema(
            {
                "message_ref": string("Referência opaca da mensagem.", max_length=80),
                "text": string("Resposta exata.", max_length=4000),
            },
            ("message_ref", "text"),
        ),
    ),
    _tool(
        "whatsapp.react",
        "whatsapp_react_message",
        "Propõe reagir a uma mensagem por sua referência opaca.",
        "whatsapp.react",
        object_schema(
            {
                "message_ref": string("Referência opaca da mensagem.", max_length=80),
                "reaction": string("Emoji exato.", max_length=16),
            },
            ("message_ref", "reaction"),
        ),
    ),
    _tool(
        "whatsapp.mark_read",
        "whatsapp_mark_read",
        "Propõe marcar uma conversa ou mensagens específicas como lidas.",
        "whatsapp.mark_read",
        object_schema(
            {
                "chat_ref": string("Referência opaca da conversa.", max_length=160),
                "message_refs": string_array(
                    "Referências opacas opcionais das mensagens.", max_items=50
                ),
            },
            ("chat_ref",),
        ),
    ),
    _tool(
        "whatsapp.send_media",
        "whatsapp_send_media",
        "Propõe enviar mídia HTTPS para uma conversa WhatsApp.",
        "whatsapp.media",
        object_schema(
            {
                **_DESTINATION,
                "media_type": string(
                    "Tipo da mídia.", enum=("image", "video", "audio", "document")
                ),
                "url": string("URL HTTPS da mídia.", max_length=2000),
                "caption": string("Legenda.", max_length=4000),
                "file_name": string("Nome do arquivo.", max_length=240),
                "mimetype": string("MIME type.", max_length=120),
            },
            ("media_type", "url"),
        ),
    ),
    _tool(
        "whatsapp.poll",
        "whatsapp_create_poll",
        "Propõe criar uma enquete WhatsApp.",
        "whatsapp.poll",
        object_schema(
            {
                **_DESTINATION,
                "question": string("Pergunta da enquete.", max_length=4000),
                "options": string_array("Opções.", max_items=20),
                "selectable_count": integer(
                    "Quantidade selecionável.", minimum=1, maximum=20
                ),
            },
            ("question", "options"),
        ),
    ),
)


_CHAT_TOGGLE = {
    "chat_ref": string("Referência opaca da conversa.", max_length=160),
    "enabled": boolean("Novo estado."),
}
_CHAT_TOOLS = tuple(
    _tool(
        f"whatsapp.{operation}",
        f"whatsapp_{operation}_chat",
        f"Propõe alterar o estado {operation} de uma conversa WhatsApp.",
        f"whatsapp.{operation}",
        object_schema(_CHAT_TOGGLE, ("chat_ref", "enabled")),
    )
    for operation in ("archive", "pin", "mute")
)
_ADMIN_TOOLS = _CHAT_TOOLS + (
    _tool(
        "whatsapp.group_create",
        "whatsapp_create_group",
        "Propõe criar um grupo WhatsApp.",
        "whatsapp.group_create",
        object_schema(
            {
                "subject": string("Nome do grupo.", max_length=240),
                "contact_names": string_array(
                    "Nomes dos participantes.", max_items=100
                ),
            },
            ("subject", "contact_names"),
        ),
    ),
    _tool(
        "whatsapp.group_subject",
        "whatsapp_change_group_subject",
        "Propõe alterar o assunto de um grupo WhatsApp.",
        "whatsapp.group_subject",
        object_schema(
            {
                "chat_ref": string("Referência opaca do grupo.", max_length=160),
                "subject": string("Novo assunto.", max_length=240),
            },
            ("chat_ref", "subject"),
        ),
    ),
    _tool(
        "whatsapp.privacy_update",
        "whatsapp_update_privacy",
        "Propõe alterar uma configuração de privacidade WhatsApp.",
        "whatsapp.privacy_update",
        object_schema(
            {
                "setting": string("Configuração.", max_length=40),
                "value": string("Novo valor.", max_length=40),
            },
            ("setting", "value"),
        ),
    ),
    _tool(
        "whatsapp.profile_status",
        "whatsapp_update_profile_status",
        "Propõe atualizar o recado do perfil WhatsApp.",
        "whatsapp.profile_status",
        object_schema({"text": string("Novo recado.", max_length=4000)}, ("text",)),
    ),
    _tool(
        "whatsapp.broadcast",
        "whatsapp_publish_status",
        "Propõe publicar um status/broadcast WhatsApp.",
        "whatsapp.broadcast",
        object_schema(
            {
                "text": string("Texto exato.", max_length=4000),
                "audience_refs": string_array(
                    "Referências opacas opcionais da audiência.", max_items=100
                ),
            },
            ("text",),
        ),
    ),
)


def whatsapp_message_tools() -> tuple[ToolDefinition, ...]:
    return _MESSAGE_TOOLS


def whatsapp_admin_tools() -> tuple[ToolDefinition, ...]:
    return _ADMIN_TOOLS
