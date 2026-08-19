"""Approved WhatsApp mutations executed exclusively through AceleraChat."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from openjarvis.server.jarvis_agent.adapters.acelerachat.capabilities import (
    AceleraChatCapabilities,
    ChannelSnapshot,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.client import (
    AceleraChatClient,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.models import Message
from openjarvis.server.jarvis_agent.adapters.acelerachat.references import (
    AceleraChatReferences,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.whatsapp_directory import (
    WhatsAppDirectory,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.whatsapp_targeting import (
    WhatsAppMutationTargeting,
)
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import (
    AdapterResult,
    ExternalOperation,
    PreparedToolCall,
)
from openjarvis.server.jarvis_agent.domain.states import ActionState

MUTATION_TOOL_IDS = frozenset(
    {
        "whatsapp.send_text",
        "whatsapp.reply",
        "whatsapp.react",
        "whatsapp.mark_read_provider",
        "whatsapp.send_media",
        "whatsapp.mark_read_internal",
    }
)


class AceleraChatWhatsAppMutations:
    def __init__(
        self,
        client: AceleraChatClient,
        capabilities: AceleraChatCapabilities,
        references: AceleraChatReferences,
        directory: WhatsAppDirectory,
    ) -> None:
        self._client = client
        self._capabilities = capabilities
        self._references = references
        self._directory = directory
        self._targeting = WhatsAppMutationTargeting(
            references, directory, self._require_channel
        )

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        if tool_id in {"whatsapp.send_text", "whatsapp.send_media"}:
            return self._targeting.prepare_send(tool_id, arguments, context)
        if tool_id in {"whatsapp.reply", "whatsapp.react"}:
            return self._targeting.prepare_message_action(tool_id, arguments, context)
        if tool_id in {
            "whatsapp.mark_read_provider",
            "whatsapp.mark_read_internal",
        }:
            payload, target = self._targeting.conversation_reference(arguments, context)
            risk = (
                "envia recibos de leitura externos e atualiza o AceleraChat"
                if tool_id == "whatsapp.mark_read_provider"
                else "altera somente a leitura interna do AceleraChat"
            )
            return PreparedToolCall(
                payload,
                {
                    "provider": "AceleraChat",
                    "channel": "WhatsApp",
                    "target": target,
                    "risk": risk,
                },
            )
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta WhatsApp indisponível.")

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        snapshot = self._require_channel(expected=int(arguments["inbox_id"]))
        if tool_id in {"whatsapp.send_text", "whatsapp.send_media"}:
            return self._send(tool_id, arguments, context, snapshot)
        if tool_id == "whatsapp.reply":
            return self._create_message(
                arguments,
                context,
                snapshot,
                {
                    "content": str(arguments["text"]),
                    "private": False,
                    "reply_to_message_id": int(arguments["message_id"]),
                },
            )
        if tool_id == "whatsapp.react":
            response = self._client.react_message(
                int(arguments["conversation_id"]),
                int(arguments["message_id"]),
                str(arguments["reaction"]),
                idempotency_key=f"jarvis:{context.request_id}",
            )
            data = self._response_data(response)
            return AdapterResult("completed", "Reação confirmada pelo WhatsApp.", data)
        if tool_id == "whatsapp.mark_read_provider":
            response = self._client.mark_provider_read(
                int(arguments["conversation_id"]),
                idempotency_key=f"jarvis:{context.request_id}",
            )
            data = self._response_data(response)
            return AdapterResult(
                "completed", "Recibos de leitura confirmados pelo WhatsApp.", data
            )
        if tool_id == "whatsapp.mark_read_internal":
            return self._mark_internal(arguments, context)
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta WhatsApp indisponível.")

    def _send(
        self,
        tool_id: str,
        arguments: Mapping[str, Any],
        context: AdapterContext,
        snapshot: ChannelSnapshot,
    ) -> AdapterResult:
        values = dict(arguments)
        if "conversation_id" not in values:
            conversation = self._directory.resolve_or_create(
                phone_number=str(values["phone_number"]),
                contact_name=str(values.get("contact_name") or ""),
                inbox_id=snapshot.inbox.id,
                request_id=context.request_id,
            )
            values["conversation_id"] = conversation.id
        message = (
            {"content": str(values["text"]), "private": False}
            if tool_id == "whatsapp.send_text"
            else {
                "content": str(values.get("caption") or ""),
                "private": False,
                "remote_attachment": {"url": str(values["url"])},
            }
        )
        return self._create_message(values, context, snapshot, message)

    def _create_message(
        self,
        arguments: Mapping[str, Any],
        context: AdapterContext,
        snapshot: ChannelSnapshot,
        message_payload: Mapping[str, Any],
    ) -> AdapterResult:
        response = self._client.create_message(
            int(arguments["conversation_id"]),
            message_payload,
            idempotency_key=f"jarvis:{context.request_id}:message",
        )
        result = response.get("result")
        data = response.get("data")
        if not isinstance(result, Mapping) or not isinstance(data, Mapping):
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID", "O aceite do AceleraChat é inválido."
            )
        if result.get("state") != "accepted":
            raise JarvisAgentError(
                "PROVIDER_UNAVAILABLE", "O AceleraChat recusou a mensagem."
            )
        try:
            message = Message.model_validate(data)
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou uma mensagem inválida.",
            ) from exc
        message_ref = self._references.create(
            partition_key=context.partition_key,
            source="whatsapp",
            kind="message",
            resource_id=message.id,
            inbox_id=snapshot.inbox.id,
            conversation_id=message.conversation_id,
        )
        return AdapterResult(
            "accepted",
            "Mensagem aceita pelo AceleraChat; entrega aguardando confirmação.",
            {"message_ref": message_ref, "delivery": "pending"},
            {"message": message_ref},
            ActionState.ACCEPTED,
            ExternalOperation("acelerachat", "Message", str(message.id)),
        )

    def _mark_internal(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        response = self._client.mark_conversation_read(
            int(arguments["conversation_id"]),
            idempotency_key=f"jarvis:{context.request_id}",
        )
        data = self._response_data(response)
        if data.get("provider_receipt_sent") is not False:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O marcador de leitura retornou contrato inválido.",
            )
        return AdapterResult(
            "completed",
            "Conversa marcada como lida dentro do AceleraChat.",
            {"provider_receipt_sent": False},
        )

    def _require_channel(
        self, *, expected: int | None = None, inbox_name: str = ""
    ) -> ChannelSnapshot:
        snapshot = self._capabilities.select(
            "acelerachat_whatsapp",
            inbox_id=expected,
            inbox_name=inbox_name,
            force=True,
        )
        inbox = snapshot.inbox
        if inbox is None or not (
            inbox.connection.operational or inbox.connection.connected
        ):
            raise JarvisAgentError(
                "SOURCE_DISCONNECTED", "O WhatsApp do AceleraChat está indisponível."
            )
        return snapshot

    @staticmethod
    def _response_data(response: Mapping[str, Any]) -> dict[str, Any]:
        data = response.get("data")
        if not isinstance(data, Mapping):
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID", "O AceleraChat retornou contrato inválido."
            )
        return dict(data)


__all__ = ["AceleraChatWhatsAppMutations", "MUTATION_TOOL_IDS"]
