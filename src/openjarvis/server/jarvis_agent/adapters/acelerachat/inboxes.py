"""Account-scoped tools for every authorized AceleraChat inbox."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from openjarvis.server.jarvis_agent.adapters.acelerachat.capabilities import (
    AceleraChatCapabilities,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.client import (
    AceleraChatClient,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.models import (
    Conversation,
    Inbox,
    Message,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.presentation import (
    present_conversation,
    present_message,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.references import (
    AceleraChatReferences,
)
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import (
    AdapterResult,
    ExternalOperation,
    PreparedToolCall,
)
from openjarvis.server.jarvis_agent.domain.states import ActionState


class AceleraChatInboxTools:
    def __init__(
        self,
        client: AceleraChatClient,
        capabilities: AceleraChatCapabilities,
        references: AceleraChatReferences,
    ) -> None:
        self._client = client
        self._capabilities = capabilities
        self._references = references

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        if tool_id in {
            "acelerachat.list_inboxes",
            "acelerachat.list_conversations",
        }:
            return PreparedToolCall(dict(arguments), {"source": "AceleraChat"})

        resolved = self._resolve_conversation(arguments, context)
        payload = {
            "conversation_id": resolved["conversation_id"] or resolved["resource_id"],
            "inbox_id": resolved["inbox_id"],
        }
        if tool_id == "acelerachat.read_conversation":
            payload["limit"] = int(arguments.get("limit", 50))
            return PreparedToolCall(payload, {"source": "AceleraChat"})
        if tool_id == "acelerachat.send_message":
            text = str(arguments.get("text") or "").strip()
            if not text:
                raise JarvisAgentError(
                    "INVALID_REQUEST", "A mensagem não pode ser vazia."
                )
            payload["text"] = text
            conversation = self._conversation(
                self._client.get_conversation(int(payload["conversation_id"]))
            )
            return PreparedToolCall(
                payload,
                {
                    "provider": "AceleraChat",
                    "channel": conversation.inbox.channel_type,
                    "inbox": conversation.inbox.name,
                    "target": conversation.contact.name
                    if conversation.contact
                    else "conversa selecionada",
                    "message": text,
                    "risk": "envio externo pelo canal da caixa",
                },
            )
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta indisponível.")

    def execute(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        if tool_id == "acelerachat.list_inboxes":
            return self._list_inboxes()
        if tool_id == "acelerachat.list_conversations":
            return self._list_conversations(arguments, context)
        if tool_id == "acelerachat.read_conversation":
            return self._read(arguments, context)
        if tool_id == "acelerachat.send_message":
            return self._send(arguments, context)
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta indisponível.")

    def _list_inboxes(self) -> AdapterResult:
        snapshot = self._capabilities.channel("acelerachat_inboxes", force=True)
        values = [self._present_inbox(inbox) for inbox in snapshot.inboxes]
        return AdapterResult(
            "completed",
            f"{len(values)} caixa(s) autorizada(s) no AceleraChat.",
            {"inboxes": values},
        )

    def _list_conversations(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        limit = min(int(arguments.get("limit", 25)), 25)
        inboxes = self._selected_inboxes(arguments, "conversations.search")
        conversations: dict[int, Conversation] = {}
        for inbox in inboxes:
            for value in self._client.search_conversations(
                inbox_id=inbox.id, limit=limit
            ):
                conversation = self._conversation(value)
                conversations[conversation.id] = conversation
        ordered = sorted(
            conversations.values(),
            key=lambda item: item.last_activity_at or item.updated_at,
            reverse=True,
        )[:limit]
        values: list[dict[str, Any]] = []
        references: dict[str, str] = {}
        for index, conversation in enumerate(ordered, start=1):
            value, reference = present_conversation(
                conversation,
                source="acelerachat",
                partition_key=context.partition_key,
                references=self._references,
            )
            value["inbox"] = conversation.inbox.name
            value["channel_type"] = conversation.inbox.channel_type
            values.append(value)
            references[f"conversation_{index}"] = reference
        return AdapterResult(
            "completed",
            f"{len(values)} conversa(s) encontrada(s).",
            {"conversations": values, "untrusted_external_data": True},
            references,
        )

    def _read(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        inbox_id = int(arguments["inbox_id"])
        self._capabilities.select(
            "acelerachat_inboxes",
            inbox_id=inbox_id,
            required_capability="messages.read",
            force=True,
        )
        messages = self._messages(
            self._client.list_messages(
                int(arguments["conversation_id"]),
                min(int(arguments.get("limit", 50)), 100),
            )
        )
        values: list[dict[str, Any]] = []
        references: dict[str, str] = {}
        for index, message in enumerate(messages, start=1):
            value, created = present_message(
                message,
                source="acelerachat",
                inbox_id=inbox_id,
                partition_key=context.partition_key,
                references=self._references,
            )
            values.append(value)
            references[f"message_{index}"] = created["message"]
        return AdapterResult(
            "completed",
            f"{len(values)} mensagem(ns) lida(s).",
            {"messages": values, "untrusted_external_data": True},
            references,
        )

    def _send(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        inbox_id = int(arguments["inbox_id"])
        self._capabilities.select(
            "acelerachat_inboxes",
            inbox_id=inbox_id,
            required_capability="messages.send",
            force=True,
        )
        response = self._client.create_message(
            int(arguments["conversation_id"]),
            {"content": str(arguments["text"]), "private": False},
            idempotency_key=f"jarvis:{context.request_id}:message",
        )
        result = response.get("result")
        data = response.get("data")
        if (
            not isinstance(result, Mapping)
            or result.get("state") != "accepted"
            or not isinstance(data, Mapping)
        ):
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID", "O aceite do AceleraChat é inválido."
            )
        message = self._message(dict(data))
        reference = self._references.create(
            partition_key=context.partition_key,
            source="acelerachat",
            kind="message",
            resource_id=message.id,
            inbox_id=inbox_id,
            conversation_id=message.conversation_id,
        )
        return AdapterResult(
            "accepted",
            "Mensagem aceita pelo AceleraChat; entrega aguardando confirmação.",
            {"message_ref": reference, "delivery": "pending"},
            {"message": reference},
            ActionState.ACCEPTED,
            ExternalOperation("acelerachat", "Message", str(message.id)),
        )

    def _selected_inboxes(
        self, arguments: Mapping[str, Any], capability: str
    ) -> tuple[Inbox, ...]:
        raw_id = arguments.get("inbox_id")
        inbox_name = str(arguments.get("inbox_name") or "")
        if raw_id is not None or inbox_name:
            selected = self._capabilities.select(
                "acelerachat_inboxes",
                inbox_id=int(raw_id) if raw_id is not None else None,
                inbox_name=inbox_name,
                required_capability=capability,
            )
            return (selected.inbox,)
        snapshot = self._capabilities.channel("acelerachat_inboxes")
        return tuple(
            inbox
            for inbox in snapshot.operational_inboxes
            if inbox.capabilities.get(capability)
            and inbox.capabilities[capability].supported
        )

    def _resolve_conversation(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> dict[str, int | None]:
        return self._references.resolve(
            str(arguments.get("conversation_ref") or ""),
            partition_key=context.partition_key,
            source="acelerachat",
            kind="conversation",
        )

    @staticmethod
    def _present_inbox(inbox: Inbox) -> dict[str, Any]:
        return {
            "id": inbox.id,
            "name": inbox.name,
            "channel_type": inbox.channel_type,
            "provider": inbox.connection.provider,
            "status": inbox.connection.state,
            "connected": inbox.connection.connected,
            "operational": bool(
                inbox.connection.operational or inbox.connection.connected
            ),
        }

    @staticmethod
    def _conversation(value: Mapping[str, Any]) -> Conversation:
        try:
            return Conversation.model_validate(value)
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID", "O AceleraChat retornou conversa inválida."
            ) from exc

    @staticmethod
    def _messages(values: list[dict[str, Any]]) -> list[Message]:
        return [AceleraChatInboxTools._message(value) for value in values]

    @staticmethod
    def _message(value: Mapping[str, Any]) -> Message:
        try:
            return Message.model_validate(value)
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID", "O AceleraChat retornou mensagem inválida."
            ) from exc


__all__ = ["AceleraChatInboxTools"]
