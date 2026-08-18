"""Bounded, provider-ID-free results returned to Gemini."""

from __future__ import annotations

from typing import Any

from openjarvis.server.jarvis_agent.adapters.acelerachat.models import (
    Contact,
    Conversation,
    Message,
)
from openjarvis.server.jarvis_agent.adapters.acelerachat.references import (
    AceleraChatReferences,
)

_CONTENT_LIMIT = 2_000


def present_conversation(
    conversation: Conversation,
    *,
    source: str,
    partition_key: str,
    references: AceleraChatReferences,
) -> tuple[dict[str, Any], str]:
    reference = references.create(
        partition_key=partition_key,
        source=source,
        kind="conversation",
        resource_id=conversation.id,
        inbox_id=conversation.inbox.id,
        conversation_id=conversation.id,
        metadata={"status": conversation.status},
    )
    contact = conversation.contact
    return (
        {
            "conversation_ref": reference,
            "contact": contact.name if contact else None,
            "status": conversation.status,
            "labels": conversation.labels[:20],
            "last_activity_at": conversation.last_activity_at,
        },
        reference,
    )


def present_contact(
    contact: Contact,
    conversation: Conversation,
    *,
    source: str,
    partition_key: str,
    references: AceleraChatReferences,
) -> tuple[dict[str, Any], str]:
    reference = references.create(
        partition_key=partition_key,
        source=source,
        kind="contact",
        resource_id=contact.id,
        inbox_id=conversation.inbox.id,
        conversation_id=conversation.id,
        metadata={"blocked": contact.blocked},
    )
    conversation_value, conversation_ref = present_conversation(
        conversation,
        source=source,
        partition_key=partition_key,
        references=references,
    )
    return (
        {
            "contact_ref": reference,
            "conversation_ref": conversation_ref,
            "name": contact.name,
            "email": contact.email if source == "email" else None,
            "phone": contact.phone_number if source == "whatsapp" else None,
            "blocked": contact.blocked,
            "conversation_status": conversation_value["status"],
        },
        reference,
    )


def present_message(
    message: Message,
    *,
    source: str,
    inbox_id: int,
    partition_key: str,
    references: AceleraChatReferences,
) -> tuple[dict[str, Any], dict[str, str]]:
    message_ref = references.create(
        partition_key=partition_key,
        source=source,
        kind="message",
        resource_id=message.id,
        inbox_id=inbox_id,
        conversation_id=message.conversation_id,
        metadata={"status": message.status, "unread": message.unread},
    )
    conversation_ref = references.create(
        partition_key=partition_key,
        source=source,
        kind="conversation",
        resource_id=message.conversation_id,
        inbox_id=inbox_id,
        conversation_id=message.conversation_id,
    )
    email = message.email
    value = {
        "message_ref": message_ref,
        "conversation_ref": conversation_ref,
        "direction": message.message_type,
        "content": (message.content or "")[:_CONTENT_LIMIT],
        "sender": message.sender.name if message.sender else None,
        "sender_email": message.sender.email
        if message.sender and source == "email"
        else None,
        "subject": email.subject if email else None,
        "to": email.to[:25] if email else [],
        "cc": email.cc[:25] if email else [],
        "status": message.status,
        "delivery": message.delivery.result_state,
        "unread": message.unread,
        "attachments": [
            {
                "type": attachment.file_type,
                "size": attachment.file_size,
                "extension": attachment.extension,
            }
            for attachment in message.attachments[:20]
        ],
        "created_at": message.created_at,
    }
    return value, {"message": message_ref, "conversation": conversation_ref}
