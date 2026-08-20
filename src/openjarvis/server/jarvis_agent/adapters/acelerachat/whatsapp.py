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
from openjarvis.server.jarvis_agent.adapters.acelerachat.whatsapp_contacts import (
    CONTACT_MUTATION_TOOL_IDS,
    AceleraChatWhatsAppContacts,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.whatsapp_directory import (
    WhatsAppDirectory,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.whatsapp_write import (
    MUTATION_TOOL_IDS,
    AceleraChatWhatsAppMutations,
)
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import AdapterResult, PreparedToolCall


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
        self._contacts = AceleraChatWhatsAppContacts(
            capabilities, references, self._directory
        )
        self._mutations = AceleraChatWhatsAppMutations(
            client, capabilities, references, self._directory
        )

    def prepare(
        self, tool_id: str, arguments: Mapping[str, Any], context: AdapterContext
    ) -> PreparedToolCall:
        if tool_id in {
            "whatsapp.status",
            "whatsapp.search_contacts",
            "whatsapp.search_chats",
        }:
            return PreparedToolCall(dict(arguments), {"source": "AceleraChat WhatsApp"})
        if tool_id in MUTATION_TOOL_IDS:
            return self._mutations.prepare(tool_id, arguments, context)
        if tool_id in CONTACT_MUTATION_TOOL_IDS:
            return self._contacts.prepare(arguments, context)
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
        else:
            raise JarvisAgentError(
                "INVALID_REQUEST", "Selecione uma conversa WhatsApp válida."
            )
        payload: dict[str, Any] = {
            "conversation_id": conversation_id,
            "inbox_id": inbox_id,
        }
        if tool_id in {"whatsapp.read_conversation", "whatsapp.summarize_conversation"}:
            payload["limit"] = int(arguments.get("limit", 50))
            return PreparedToolCall(payload, {"source": "AceleraChat WhatsApp"})
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
        if tool_id in MUTATION_TOOL_IDS:
            return self._mutations.execute(tool_id, arguments, context)
        if tool_id in CONTACT_MUTATION_TOOL_IDS:
            return self._contacts.execute(arguments, context)
        raise JarvisAgentError("TOOL_UNAVAILABLE", "Ferramenta WhatsApp indisponível.")

    def _status(self) -> AdapterResult:
        snapshot = self._capabilities.channel("acelerachat_whatsapp", force=True)
        inboxes = [
            {
                "id": inbox.id,
                "name": inbox.name,
                "status": inbox.connection.state,
                "connected": inbox.connection.connected,
                "operational": bool(
                    inbox.connection.operational or inbox.connection.connected
                ),
                "provider": inbox.connection.provider,
            }
            for inbox in snapshot.inboxes
        ]
        return AdapterResult(
            "completed",
            f"{len(inboxes)} caixa(s) WhatsApp autorizada(s) no AceleraChat.",
            {
                "status": snapshot.status,
                "connected": snapshot.connected,
                "operational": snapshot.operational,
                "reason": snapshot.reason,
                "inboxes": inboxes,
            },
        )

    def _search_contacts(
        self, arguments: Mapping[str, Any], context: AdapterContext
    ) -> AdapterResult:
        query = str(arguments["query"]).strip()
        limit = min(int(arguments.get("limit", 10)), 25)
        snapshot = self._require_channel(
            expected=self._optional_inbox_id(arguments),
            inbox_name=str(arguments.get("inbox_name") or ""),
        )
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
        snapshot = self._require_channel(
            expected=self._optional_inbox_id(arguments),
            inbox_name=str(arguments.get("inbox_name") or ""),
        )
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

    def _require_channel(
        self,
        *,
        expected: int | None = None,
        inbox_name: str = "",
        force: bool = False,
    ) -> ChannelSnapshot:
        snapshot = self._capabilities.select(
            "acelerachat_whatsapp",
            inbox_id=expected,
            inbox_name=inbox_name,
            force=force,
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
    def _optional_inbox_id(arguments: Mapping[str, Any]) -> int | None:
        value = arguments.get("inbox_id")
        return int(value) if value is not None else None

    @staticmethod
    def _messages(values: list[dict[str, Any]]) -> list[Message]:
        try:
            return [Message.model_validate(value) for value in values]
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou mensagens inválidas.",
            ) from exc
