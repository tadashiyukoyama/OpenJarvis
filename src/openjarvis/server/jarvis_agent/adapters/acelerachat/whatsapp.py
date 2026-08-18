"""Typed WhatsApp operations executed through AceleraChat."""

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
from openjarvis.server.jarvis_agent.adapters.acelerachat.presentation import (
    present_message,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.references import (
    AceleraChatReferences,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.whatsapp_directory import (
    WhatsAppDirectory,
)
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import (
    AdapterResult,
    ExternalOperation,
    PreparedToolCall,
)
from openjarvis.server.jarvis_agent.domain.states import ActionState


class AceleraChatWhatsAppTools:
    def __init__(
        self,
        client: AceleraChatClient,
        capabilities: AceleraChatCapabilities,
        references: AceleraChatReferences,
    ) -> None:
        self._client = client
        self._capabilities = capabilities
        self._references = references
        self._directory = WhatsAppDirectory(client, references)

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        if tool_id in {
            "whatsapp.status",
            "whatsapp.search_contacts",
            "whatsapp.search_chats",
        }:
            return PreparedToolCall(dict(arguments), {"source": "AceleraChat WhatsApp"})
        reference = str(arguments.get("conversation_ref") or "").strip()
        if reference:
            resolved = self._references.resolve(
                reference,
                partition_key=context.partition_key,
                source="whatsapp",
                kind=("conversation", "contact"),
            )
            conversation_id = resolved["conversation_id"] or resolved["resource_id"]
            inbox_id = int(resolved["inbox_id"])
            target = "conversa selecionada"
        elif tool_id == "whatsapp.send_text":
            snapshot = self._require_channel()
            conversation, target = self._directory.resolve_unique(
                str(arguments.get("contact_name") or ""), snapshot.inbox.id
            )
            conversation_id = conversation.id
            inbox_id = conversation.inbox.id
        else:
            raise JarvisAgentError(
                "INVALID_REQUEST", "Selecione uma conversa WhatsApp válida."
            )
        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "inbox_id": inbox_id,
        }
        if tool_id == "whatsapp.send_text":
            payload["text"] = str(arguments["text"]).strip()
            return PreparedToolCall(
                payload,
                {
                    "provider": "AceleraChat",
                    "channel": "WhatsApp",
                    "target": target,
                    "message": payload["text"],
                    "risk": "envio externo assíncrono",
                },
            )
        if tool_id in {"whatsapp.read_conversation", "whatsapp.summarize_conversation"}:
            payload["limit"] = int(arguments.get("limit", 50))
            return PreparedToolCall(payload, {"source": "AceleraChat WhatsApp"})
        if tool_id == "whatsapp.mark_read_internal":
            return PreparedToolCall(
                payload,
                {
                    "provider": "AceleraChat",
                    "channel": "WhatsApp",
                    "target": target,
                    "risk": "marca apenas a caixa do AceleraChat como lida",
                },
            )
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta WhatsApp indisponível.")

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        if tool_id == "whatsapp.status":
            return self._status()
        if tool_id == "whatsapp.search_contacts":
            return self._search_contacts(arguments, context)
        if tool_id == "whatsapp.search_chats":
            return self._search_chats(arguments, context)
        if tool_id in {"whatsapp.read_conversation", "whatsapp.summarize_conversation"}:
            return self._read(arguments, context)
        if tool_id == "whatsapp.send_text":
            return self._send(arguments, context)
        if tool_id == "whatsapp.mark_read_internal":
            return self._mark_read(arguments, context)
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta WhatsApp indisponível.")

    def _status(self) -> AdapterResult:
        snapshot = self._capabilities.channel("acelerachat_whatsapp", force=True)
        inbox = snapshot.inbox
        return AdapterResult(
            "completed",
            f"WhatsApp AceleraChat: {snapshot.status}.",
            {
                "status": snapshot.status,
                "connected": snapshot.connected,
                "operational": bool(
                    inbox
                    and (inbox.connection.operational or inbox.connection.connected)
                ),
                "provider": inbox.connection.provider if inbox else None,
                "reason": snapshot.reason,
            },
        )

    def _search_contacts(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        query = str(arguments["query"]).strip()
        limit = min(int(arguments.get("limit", 10)), 25)
        snapshot = self._require_channel()
        return self._directory.search_contacts(
            query=query,
            limit=limit,
            inbox_id=snapshot.inbox.id,
            context=context,
        )

    def _search_chats(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        query = str(arguments.get("query") or "").strip()
        limit = min(int(arguments.get("limit", 10)), 25)
        snapshot = self._require_channel()
        return self._directory.search_chats(
            query=query,
            limit=limit,
            inbox_id=snapshot.inbox.id,
            context=context,
        )

    def _read(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        snapshot = self._require_channel(expected=int(arguments["inbox_id"]))
        messages = self._messages(
            self._client.list_messages(
                int(arguments["conversation_id"]),
                min(int(arguments.get("limit", 50)), 100),
            )
        )
        values: list[dict[str, Any]] = []
        refs: dict[str, str] = {}
        for index, message in enumerate(messages):
            value, created = present_message(
                message,
                source="whatsapp",
                inbox_id=snapshot.inbox.id,
                partition_key=context.partition_key,
                references=self._references,
            )
            values.append(value)
            refs[f"message_{index + 1}"] = created["message"]
        return AdapterResult(
            "completed",
            f"{len(values)} mensagem(ns) WhatsApp lida(s).",
            {"messages": values, "untrusted_external_data": True},
            refs,
        )

    def _send(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        snapshot = self._require_channel(
            expected=int(arguments["inbox_id"]), force=True
        )
        response = self._client.create_message(
            int(arguments["conversation_id"]),
            {"content": str(arguments["text"]), "private": False},
            idempotency_key=f"jarvis:{context.request_id}",
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

    def _mark_read(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        self._require_channel(expected=int(arguments["inbox_id"]), force=True)
        response = self._client.mark_conversation_read(
            int(arguments["conversation_id"]),
            idempotency_key=f"jarvis:{context.request_id}",
        )
        data = response.get("data")
        if (
            not isinstance(data, Mapping)
            or data.get("provider_receipt_sent") is not False
        ):
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
        self, *, expected: int | None = None, force: bool = False
    ) -> ChannelSnapshot:
        snapshot = self._capabilities.channel("acelerachat_whatsapp", force=force)
        inbox = snapshot.inbox
        if inbox is None or not (
            inbox.connection.operational or inbox.connection.connected
        ):
            raise JarvisAgentError(
                "SOURCE_DISCONNECTED", "O WhatsApp do AceleraChat está indisponível."
            )
        if expected is not None and inbox.id != expected:
            raise JarvisAgentError("MANIFEST_STALE", "A caixa WhatsApp ativa mudou.")
        return snapshot

    @staticmethod
    def _messages(values: list[dict[str, Any]]) -> list[Message]:
        try:
            return [Message.model_validate(value) for value in values]
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou mensagens inválidas.",
            ) from exc
