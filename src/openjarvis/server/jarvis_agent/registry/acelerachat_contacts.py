"""AceleraChat contact tools kept separate from the channel registry."""

from __future__ import annotations

from openjarvis.server.jarvis_agent.domain.models import ToolDefinition
from openjarvis.server.jarvis_agent.domain.states import Effect
from openjarvis.server.jarvis_agent.registry.acelerachat_schemas import (
    WHATSAPP_NEW_CONTACT,
)
from openjarvis.server.jarvis_agent.registry.schemas import object_schema


def acelerachat_contact_tools() -> tuple[ToolDefinition, ...]:
    return (
        ToolDefinition(
            "whatsapp.save_contact",
            "whatsapp_save_contact",
            "Propõe salvar ou reutilizar um contato e associá-lo à caixa WhatsApp "
            "do AceleraChat, sem enviar mensagem.",
            "whatsapp",
            "acelerachat_whatsapp",
            "acelerachat",
            "conversations.create",
            Effect.MUTATION,
            20.0,
            object_schema(WHATSAPP_NEW_CONTACT, ("phone_number",)),
        ),
    )


__all__ = ["acelerachat_contact_tools"]
