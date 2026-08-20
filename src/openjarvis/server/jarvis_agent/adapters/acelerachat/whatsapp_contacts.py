"""Approved contact persistence through the AceleraChat WhatsApp boundary."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.adapters.acelerachat.capabilities import (
    AceleraChatCapabilities,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.presentation import (
    present_contact,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.references import (
    AceleraChatReferences,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.whatsapp_directory import (
    WhatsAppDirectory,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.whatsapp_values import (
    normalize_e164,
)
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import AdapterResult, PreparedToolCall

CONTACT_MUTATION_TOOL_IDS = frozenset({"whatsapp.save_contact"})


class AceleraChatWhatsAppContacts:
    """Prepare and persist one contact without dispatching a provider message."""

    def __init__(
        self,
        capabilities: AceleraChatCapabilities,
        references: AceleraChatReferences,
        directory: WhatsAppDirectory,
    ) -> None:
        self._capabilities = capabilities
        self._references = references
        self._directory = directory

    def prepare(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        del context
        phone_number = normalize_e164(arguments.get("phone_number"))
        contact_name = str(arguments.get("contact_name") or "").strip()
        if len(contact_name) > 240:
            raise JarvisAgentError(
                "INVALID_REQUEST", "O nome do contato é muito longo."
            )
        snapshot = self._select_inbox(arguments)
        target = contact_name or phone_number
        return PreparedToolCall(
            {
                "phone_number": phone_number,
                "contact_name": contact_name,
                "inbox_id": snapshot.inbox.id,
            },
            {
                "provider": "AceleraChat",
                "channel": "WhatsApp",
                "target": target,
                "phone_number": phone_number,
                "inbox": snapshot.inbox.name,
                "risk": "salva o contato e o associa à caixa; não envia mensagem",
            },
        )

    def execute(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        snapshot = self._capabilities.select(
            "acelerachat_whatsapp",
            inbox_id=int(arguments["inbox_id"]),
            required_capability="conversations.create",
            force=True,
        )
        if snapshot.inbox is None:
            raise JarvisAgentError(
                "SOURCE_DISCONNECTED", "A caixa WhatsApp está indisponível."
            )
        saved = self._directory.save_contact(
            phone_number=str(arguments["phone_number"]),
            contact_name=str(arguments.get("contact_name") or ""),
            inbox_id=snapshot.inbox.id,
            request_id=context.request_id,
        )
        value, contact_ref = present_contact(
            saved.contact,
            saved.conversation,
            source="whatsapp",
            partition_key=context.partition_key,
            references=self._references,
        )
        conversation_ref = str(value["conversation_ref"])
        return AdapterResult(
            "completed",
            "Contato salvo no AceleraChat sem enviar mensagem.",
            {
                **value,
                "contact_preexisting": saved.contact_preexisting,
                "conversation_preexisting": saved.conversation_preexisting,
                "message_sent": False,
            },
            {"contact": contact_ref, "conversation": conversation_ref},
        )

    def _select_inbox(self, arguments: Mapping[str, Any]):
        raw_inbox_id = arguments.get("inbox_id")
        inbox_id = int(raw_inbox_id) if raw_inbox_id is not None else None
        return self._capabilities.select(
            "acelerachat_whatsapp",
            inbox_id=inbox_id,
            inbox_name=str(arguments.get("inbox_name") or ""),
            required_capability="conversations.create",
            force=True,
        )


__all__ = ["AceleraChatWhatsAppContacts", "CONTACT_MUTATION_TOOL_IDS"]
