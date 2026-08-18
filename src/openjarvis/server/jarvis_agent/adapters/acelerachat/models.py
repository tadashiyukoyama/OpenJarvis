"""Validated, bounded projections of the AceleraChat public contract."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Capability(ContractModel):
    supported: bool = False
    mode: str = ""
    endpoint: str | None = None
    reason: str | None = None


class Connection(ContractModel):
    state: str = "unknown"
    connected: bool = False
    operational: bool = False
    source: str = ""
    provider: str | None = None
    error_code: str | None = None


class Inbox(ContractModel):
    id: int = Field(gt=0)
    name: str
    channel_type: str
    inbox_type: str
    connection: Connection
    capabilities: dict[str, Capability] = Field(default_factory=dict)


class Contact(ContractModel):
    id: int = Field(gt=0)
    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    identifier: str | None = None
    blocked: bool = False


class Delivery(ContractModel):
    status: str = "sent"
    result_state: str = "unknown"
    error: str | None = None


class EmailMetadata(ContractModel):
    thread_id: str | None = None
    subject: str | None = None
    to: list[str] = Field(default_factory=list)
    cc: list[str] = Field(default_factory=list)
    bcc: list[str] = Field(default_factory=list)


class Sender(ContractModel):
    name: str | None = None
    email: str | None = None
    type: str | None = None


class Attachment(ContractModel):
    id: int | None = None
    file_type: str = ""
    file_size: int | None = None
    extension: str | None = None


class Message(ContractModel):
    id: int = Field(gt=0)
    conversation_id: int = Field(gt=0)
    message_type: str
    content_type: str = "text"
    content: str | None = None
    private: bool = False
    status: str
    delivery: Delivery
    sender: Sender | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    email: EmailMetadata | None = None
    unread: bool = False
    created_at: str
    updated_at: str


class Conversation(ContractModel):
    id: int = Field(gt=0)
    status: str
    inbox: Inbox
    contact: Contact | None = None
    labels: list[str] = Field(default_factory=list)
    last_message: Message | None = None
    last_activity_at: str | None = None
    created_at: str
    updated_at: str


class ResourceIdentity(ContractModel):
    type: str
    id: int = Field(gt=0)
    version: str
    sequence: int = Field(ge=0)


class WebhookEnvelope(ContractModel):
    schema_version: str
    event_id: str
    event: str
    occurred_at: str
    resource: ResourceIdentity
    data: dict[str, Any]
