"""Contact and conversation lookup for the AceleraChat WhatsApp channel."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from openjarvis.server.jarvis_agent.adapters.acelerachat.client import (
    AceleraChatClient,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.models import (
    Contact,
    Conversation,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.presentation import (
    present_contact,
    present_conversation,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.references import (
    AceleraChatReferences,
)
from openjarvis.server.jarvis_agent.adapters.base import AdapterContext
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.domain.models import AdapterResult


class WhatsAppDirectory:
    def __init__(
        self, client: AceleraChatClient, references: AceleraChatReferences
    ) -> None:
        self._client = client
        self._references = references

    def search_contacts(
        self,
        *,
        query: str,
        limit: int,
        inbox_id: int,
        context: AdapterContext,
    ) -> AdapterResult:
        contacts = self._contacts(self._client.search_contacts(query, min(limit, 10)))
        values: list[dict[str, Any]] = []
        refs: dict[str, str] = {}
        for contact in contacts:
            conversations = self._conversations(
                self._client.search_conversations(
                    inbox_id=inbox_id, contact_id=contact.id, limit=5
                )
            )
            if not conversations:
                continue
            value, reference = present_contact(
                contact,
                conversations[0],
                source="whatsapp",
                partition_key=context.partition_key,
                references=self._references,
            )
            values.append(value)
            refs[f"contact_{len(values)}"] = reference
            if len(values) >= limit:
                break
        return AdapterResult(
            "completed",
            f"{len(values)} contato(s) WhatsApp encontrado(s).",
            {"contacts": values, "untrusted_external_data": True},
            refs,
        )

    def search_chats(
        self,
        *,
        query: str,
        limit: int,
        inbox_id: int,
        context: AdapterContext,
    ) -> AdapterResult:
        conversations = (
            self.conversations_for_query(query, inbox_id, limit)
            if query
            else self._conversations(
                self._client.search_conversations(inbox_id=inbox_id, limit=limit)
            )
        )
        values: list[dict[str, Any]] = []
        refs: dict[str, str] = {}
        for index, conversation in enumerate(conversations[:limit]):
            value, reference = present_conversation(
                conversation,
                source="whatsapp",
                partition_key=context.partition_key,
                references=self._references,
            )
            values.append(value)
            refs[f"conversation_{index + 1}"] = reference
        return AdapterResult(
            "completed",
            f"{len(values)} conversa(s) WhatsApp encontrada(s).",
            {"conversations": values, "untrusted_external_data": True},
            refs,
        )

    def resolve_unique(self, query: str, inbox_id: int) -> tuple[Conversation, str]:
        if not query.strip():
            raise JarvisAgentError(
                "INVALID_REQUEST", "Informe o contato ou selecione uma conversa."
            )
        conversations = self.conversations_for_query(query, inbox_id, 10)
        exact = [
            item
            for item in conversations
            if item.contact
            and (item.contact.name or "").strip().casefold() == query.strip().casefold()
        ]
        unique = {item.id: item for item in (exact or conversations)}
        if len(unique) != 1:
            message = (
                "Nenhuma conversa WhatsApp corresponde ao contato."
                if not unique
                else "O nome corresponde a mais de uma conversa; selecione uma delas."
            )
            raise JarvisAgentError("INVALID_REQUEST", message, status_code=409)
        conversation = next(iter(unique.values()))
        return (
            conversation,
            conversation.contact.name if conversation.contact else query,
        )

    def resolve_or_create(
        self,
        *,
        phone_number: str,
        contact_name: str,
        inbox_id: int,
        request_id: str,
    ) -> Conversation:
        contact_payload: dict[str, Any] = {"phone_number": phone_number}
        if contact_name.strip():
            contact_payload["name"] = contact_name.strip()
        contact = self._contact(
            self._client.create_contact(
                contact_payload,
                idempotency_key=f"jarvis:{request_id}:contact",
            )
        )
        return self._conversation(
            self._client.create_conversation(
                inbox_id,
                contact.id,
                idempotency_key=f"jarvis:{request_id}:conversation",
            )
        )

    def conversations_for_query(
        self, query: str, inbox_id: int, limit: int
    ) -> list[Conversation]:
        contacts = self._contacts(self._client.search_contacts(query, min(limit, 10)))
        conversations: dict[int, Conversation] = {}
        for contact in contacts:
            values = self._conversations(
                self._client.search_conversations(
                    inbox_id=inbox_id, contact_id=contact.id, limit=5
                )
            )
            for conversation in values:
                conversations[conversation.id] = conversation
                if len(conversations) >= limit:
                    return list(conversations.values())
        return list(conversations.values())

    @staticmethod
    def _contacts(values: list[dict[str, Any]]) -> list[Contact]:
        try:
            return [Contact.model_validate(value) for value in values]
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou contatos inválidos.",
            ) from exc

    @staticmethod
    def _contact(value: dict[str, Any]) -> Contact:
        try:
            return Contact.model_validate(value)
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou um contato inválido.",
            ) from exc

    @staticmethod
    def _conversations(values: list[dict[str, Any]]) -> list[Conversation]:
        try:
            return [Conversation.model_validate(value) for value in values]
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou conversas inválidas.",
            ) from exc

    @staticmethod
    def _conversation(value: dict[str, Any]) -> Conversation:
        try:
            return Conversation.model_validate(value)
        except ValidationError as exc:
            raise JarvisAgentError(
                "PROVIDER_RESPONSE_INVALID",
                "O AceleraChat retornou uma conversa inválida.",
            ) from exc
