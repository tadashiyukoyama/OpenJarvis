"""Target resolution and approval previews for WhatsApp mutations."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

from openjarvis.server.jarvis_agent.adapters.acelerachat.capabilities import (
    ChannelSnapshot,
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
from openjarvis.server.jarvis_agent.domain.models import PreparedToolCall


class WhatsAppMutationTargeting:
    def __init__(
        self,
        references: AceleraChatReferences,
        directory: WhatsAppDirectory,
        require_channel: Callable[..., ChannelSnapshot],
    ) -> None:
        self._references = references
        self._directory = directory
        self._require_channel = require_channel

    def prepare_send(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        payload, target = self._destination(arguments, context)
        preview: dict[str, Any] = {
            "provider": "AceleraChat",
            "channel": "WhatsApp",
            "target": target,
            "risk": "envio externo pelo WhatsApp",
        }
        if tool_id == "whatsapp.send_text":
            text = str(arguments.get("text") or "").strip()
            if not text:
                raise JarvisAgentError(
                    "INVALID_REQUEST", "A mensagem não pode ser vazia."
                )
            payload["text"] = text
            preview["message"] = text
        else:
            url = self._media_url(arguments.get("url"))
            caption = str(arguments.get("caption") or "").strip()
            payload.update({"url": url, "caption": caption})
            preview.update({"url": url, "caption": caption})
        return PreparedToolCall(payload, preview)

    def prepare_message_action(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        reference = str(arguments.get("message_ref") or "").strip()
        resolved = self._references.resolve(
            reference,
            partition_key=context.partition_key,
            source="whatsapp",
            kind="message",
        )
        conversation_id = resolved["conversation_id"]
        if conversation_id is None:
            raise JarvisAgentError("INVALID_REQUEST", "A mensagem não possui conversa.")
        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "message_id": resolved["resource_id"],
            "inbox_id": resolved["inbox_id"],
        }
        preview: dict[str, Any] = {
            "provider": "AceleraChat",
            "channel": "WhatsApp",
            "target": "mensagem selecionada",
        }
        if tool_id == "whatsapp.reply":
            text = str(arguments.get("text") or "").strip()
            if not text:
                raise JarvisAgentError(
                    "INVALID_REQUEST", "A resposta não pode ser vazia."
                )
            payload["text"] = text
            preview.update({"message": text, "risk": "resposta externa contextual"})
        else:
            reaction = str(arguments.get("reaction") or "")
            payload["reaction"] = reaction
            preview.update(
                {
                    "reaction": reaction,
                    "risk": "altera uma reação externa no WhatsApp",
                }
            )
        return PreparedToolCall(payload, preview)

    def conversation_reference(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> tuple[dict[str, Any], str]:
        reference = str(arguments.get("conversation_ref") or "").strip()
        resolved = self._references.resolve(
            reference,
            partition_key=context.partition_key,
            source="whatsapp",
            kind=("conversation", "contact"),
        )
        return (
            {
                "conversation_id": resolved["conversation_id"]
                or resolved["resource_id"],
                "inbox_id": resolved["inbox_id"],
            },
            "conversa selecionada",
        )

    def _destination(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> tuple[dict[str, Any], str]:
        reference = str(arguments.get("conversation_ref") or "").strip()
        phone = str(arguments.get("phone_number") or "").strip()
        name = str(arguments.get("contact_name") or "").strip()
        inbox_name = str(arguments.get("inbox_name") or "").strip()
        raw_inbox_id = arguments.get("inbox_id")
        inbox_id = int(raw_inbox_id) if raw_inbox_id is not None else None
        if reference:
            if phone or name or inbox_id is not None or inbox_name:
                raise JarvisAgentError(
                    "INVALID_REQUEST",
                    "Use a referência da conversa ou o destino e a caixa, não ambos.",
                )
            resolved = self._references.resolve(
                reference,
                partition_key=context.partition_key,
                source="whatsapp",
                kind=("conversation", "contact"),
            )
            return (
                {
                    "conversation_id": resolved["conversation_id"]
                    or resolved["resource_id"],
                    "inbox_id": resolved["inbox_id"],
                },
                "conversa selecionada",
            )

        snapshot = self._require_channel(
            expected=inbox_id,
            inbox_name=inbox_name,
        )
        if phone:
            normalized = self._phone_number(phone)
            return (
                {
                    "phone_number": normalized,
                    "contact_name": name,
                    "inbox_id": snapshot.inbox.id,
                },
                name or normalized,
            )
        conversation, target = self._directory.resolve_unique(name, snapshot.inbox.id)
        return (
            {"conversation_id": conversation.id, "inbox_id": conversation.inbox.id},
            target,
        )

    @staticmethod
    def _phone_number(value: str) -> str:
        return normalize_e164(value)

    @staticmethod
    def _media_url(value: Any) -> str:
        url = str(value or "").strip()
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.fragment
        ):
            raise JarvisAgentError(
                "INVALID_REQUEST", "A mídia exige uma URL HTTPS pública válida."
            )
        return url


__all__ = ["WhatsAppMutationTargeting"]
