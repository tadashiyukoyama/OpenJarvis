"""Reusable input-schema fragments for AceleraChat tools."""

from __future__ import annotations

from openjarvis.server.jarvis_agent.registry.schemas import integer, string

INBOX_SELECTOR = {
    "inbox_id": integer(
        "ID exato da caixa autorizada.", minimum=1, maximum=2_147_483_647
    ),
    "inbox_name": string("Nome exato da caixa autorizada.", max_length=240),
}

WHATSAPP_DESTINATION = {
    **INBOX_SELECTOR,
    "contact_name": string(
        "Nome exato de um contato existente ou nome opcional para um novo telefone.",
        max_length=240,
    ),
    "phone_number": string(
        "Telefone E.164, por exemplo +5511999999999; formatação visual é aceita.",
        max_length=32,
    ),
    "conversation_ref": string(
        "Referência opaca opcional da conversa.", max_length=256
    ),
}

WHATSAPP_NEW_CONTACT = {
    **INBOX_SELECTOR,
    "contact_name": string("Nome opcional do novo contato.", max_length=240),
    "phone_number": string(
        "Telefone E.164, por exemplo +5511999999999; formatação visual é aceita.",
        max_length=32,
    ),
}
