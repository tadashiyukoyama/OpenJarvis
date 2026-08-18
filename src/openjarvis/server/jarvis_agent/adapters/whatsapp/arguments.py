"""Strict argument model shared by granular WhatsApp tools."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class WhatsAppArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(default="", max_length=160)
    limit: int = Field(default=20, ge=1, le=200)
    contact_name: str = Field(default="", max_length=240)
    chat_ref: str = Field(default="", max_length=160)
    message_ref: str = Field(default="", max_length=80)
    message_refs: list[str] = Field(default_factory=list, max_length=50)
    text: str = Field(default="", max_length=4_000)
    reaction: str = Field(default="", max_length=16)
    media_type: str = Field(default="", max_length=16)
    url: str = Field(default="", max_length=2_000)
    caption: str = Field(default="", max_length=4_000)
    file_name: str = Field(default="", max_length=240)
    mimetype: str = Field(default="", max_length=120)
    question: str = Field(default="", max_length=4_000)
    options: list[str] = Field(default_factory=list, max_length=20)
    selectable_count: int = Field(default=1, ge=1, le=20)
    enabled: bool = True
    subject: str = Field(default="", max_length=240)
    contact_names: list[str] = Field(default_factory=list, max_length=100)
    setting: str = Field(default="", max_length=40)
    value: str = Field(default="", max_length=40)
    audience_refs: list[str] = Field(default_factory=list, max_length=100)
