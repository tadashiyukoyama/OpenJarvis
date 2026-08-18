"""Server-only contact and chat resolution for WhatsApp tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.services.references import ReferenceService


class WhatsAppReferences:
    def __init__(self, references: ReferenceService) -> None:
        self._references = references

    def contacts(
        self, values: list[dict[str, Any]], partition_key: str
    ) -> list[dict[str, Any]]:
        public = []
        for value in values:
            jid = str(value.get("jid") or value.get("phone_jid") or "")
            if not jid:
                continue
            display_name = str(value.get("display_name") or value.get("name") or "")
            reference = self._references.create(
                partition_key=partition_key,
                source="whatsapp",
                kind="contact",
                provider_value=jid,
                metadata={"display_name": display_name[:240]},
            )
            public.append(
                {
                    "contact_ref": reference,
                    "display_name": display_name[:240],
                    "verified_name": str(value.get("verified_name") or "")[:240],
                }
            )
        return public

    def chats(
        self, values: list[dict[str, Any]], partition_key: str
    ) -> list[dict[str, Any]]:
        public = []
        for value in values:
            jid = str(value.get("jid") or "")
            if not jid:
                continue
            display_name = str(value.get("display_name") or value.get("name") or "")
            reference = self._references.create(
                partition_key=partition_key,
                source="whatsapp",
                kind="chat",
                provider_value=jid,
                metadata={
                    "display_name": display_name[:240],
                    "is_group": bool(value.get("is_group")),
                },
            )
            public.append(
                {
                    "chat_ref": reference,
                    "display_name": display_name[:240],
                    "is_group": bool(value.get("is_group")),
                    "unread_count": int(value.get("unread_count") or 0),
                    "last_message_at": int(value.get("last_message_at") or 0),
                }
            )
        return public

    def resolve_chat(self, reference: str, partition_key: str) -> dict[str, Any]:
        return self._references.resolve(
            reference,
            partition_key=partition_key,
            source="whatsapp",
            kind=("chat", "contact"),
        )

    def resolve_destination(
        self,
        *,
        channel: Any,
        partition_key: str,
        contact_name: str,
        chat_ref: str,
    ) -> dict[str, Any]:
        if bool(contact_name.strip()) == bool(chat_ref.strip()):
            raise JarvisAgentError(
                "INVALID_REQUEST",
                "Informe exatamente um nome de contato ou uma referência de conversa.",
            )
        if chat_ref.strip():
            return self.resolve_chat(chat_ref.strip(), partition_key)
        matches = channel.search_contacts(contact_name.strip(), 10)
        if not matches:
            raise JarvisAgentError(
                "INVALID_REQUEST", "Nenhum contato WhatsApp corresponde ao nome."
            )
        folded = contact_name.strip().casefold()
        exact = [
            item
            for item in matches
            if str(item.get("display_name") or item.get("name") or "").casefold()
            == folded
        ]
        selected = exact if exact else matches
        identities = {
            str(item.get("phone_jid") or item.get("jid") or "") for item in selected
        }
        identities.discard("")
        if len(identities) != 1:
            choices = self.contacts(selected[:5], partition_key)
            raise JarvisAgentError(
                "INVALID_REQUEST",
                "Mais de um contato corresponde ao nome; escolha um contato.",
                status_code=409,
                details={"choices": choices},
            )
        value = selected[0]
        jid = next(iter(identities))
        display_name = str(
            value.get("display_name") or value.get("name") or contact_name
        )
        reference = self._references.create(
            partition_key=partition_key,
            source="whatsapp",
            kind="contact",
            provider_value=jid,
            metadata={"display_name": display_name[:240]},
        )
        return {
            "provider_value": jid,
            "metadata": {"display_name": display_name[:240]},
            "reference_id": reference,
        }


def public_messages(values: list[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep content and opaque message refs while dropping provider identifiers."""

    return [
        {
            "message_ref": str(item.get("message_ref") or ""),
            "text": str(item.get("text") or "")[:4000],
            "message_type": str(item.get("message_type") or "")[:80],
            "from_me": bool(item.get("from_me")),
            "message_at": int(item.get("message_at") or 0),
        }
        for item in values
        if item.get("message_ref")
    ]


def scrub_provider_ids(value: Any) -> Any:
    if isinstance(value, list):
        return [scrub_provider_ids(item) for item in value[:100]]
    if isinstance(value, dict):
        blocked = {
            "jid",
            "remoteJid",
            "remote_jid",
            "participant",
            "participantAlt",
            "participant_alt",
            "message_id",
            "id",
        }
        return {
            str(key): scrub_provider_ids(item)
            for key, item in value.items()
            if str(key) not in blocked
        }
    if isinstance(value, str):
        return value[:4000]
    return value
