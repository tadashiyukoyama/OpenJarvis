"""Strict HTTP contracts for the Jarvis agent API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SessionCreate(StrictModel):
    project_key: str = Field(min_length=1, max_length=1024)
    codex_thread_id: str = Field(default="", max_length=256)


class TurnCreate(StrictModel):
    generation: int = Field(gt=0)
    turn_id: str = Field(min_length=1, max_length=160)
    transcript: str = Field(min_length=1, max_length=20_000)
    final: Literal[True]


class ProposalCreate(StrictModel):
    generation: int = Field(gt=0)
    function_call_id: str = Field(min_length=1, max_length=256)
    name: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any] = Field(default_factory=dict)
    turn_id: str | None = Field(default=None, max_length=160)


class ActionDecision(StrictModel):
    session_id: str = Field(min_length=1, max_length=160)
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["approve", "deny"]


class SessionClose(StrictModel):
    generation: int = Field(gt=0)


class ContextDelete(StrictModel):
    project_key: str = Field(min_length=1, max_length=1024)
    codex_thread_id: str = Field(default="", max_length=256)


class ManifestEntryResponse(StrictModel):
    name: str
    description: str
    parameters: dict[str, Any]


class ProviderResponse(StrictModel):
    id: str
    status: str
    connected: bool
    operational: bool
    capabilities: list[str]
    reason: str | None = None


class SourceResponse(StrictModel):
    id: str
    providers: list[ProviderResponse]
    manifest_enabled: bool


class ToolResponse(StrictModel):
    id: str
    name: str
    description: str
    source: str
    provider: str
    capability: str
    effect: Literal["READ", "MUTATION", "DELEGATION"]
    timeout_seconds: float
    requires_approval: bool
    available: bool
    unavailable_reason: str | None = None
    input_schema: dict[str, Any]


class CatalogResponse(StrictModel):
    version: str
    manifest: list[ManifestEntryResponse]
    tools: list[ToolResponse]
    sources: list[SourceResponse]
    providers: list[ProviderResponse]
    availability: dict[str, tuple[bool, str | None]]


class ContextResponse(StrictModel):
    objective: str
    decisions: list[dict[str, Any]]
    pending: list[dict[str, Any]]
    results: list[dict[str, Any]]
    references: list[dict[str, Any]]


class SessionResponse(StrictModel):
    session_id: str
    generation: int
    state: Literal["ACTIVE", "CLOSED"]
    manifest_version: str
    manifest: list[ManifestEntryResponse]
    catalog: CatalogResponse
    context: ContextResponse


class TurnResponse(StrictModel):
    turn_id: str
    status: Literal["committed", "duplicate"]
    transcript_hash: str
    project_key: str | None = None


class JobResponse(StrictModel):
    job_id: str
    action_id: str
    state: Literal[
        "ACCEPTED", "RUNNING", "COMPLETED", "FAILED", "BUSY", "CANCELLED", "UNKNOWN"
    ]
    result: dict[str, Any] | None
    summary: str
    error_code: str | None
    updated_at: float


class ActionResponse(StrictModel):
    action_id: str
    session_id: str
    function_call_id: str
    tool_id: str
    payload_hash: str
    preview: dict[str, Any]
    state: Literal[
        "PROPOSED",
        "AWAITING_APPROVAL",
        "APPROVED",
        "DISPATCHING",
        "ACCEPTED",
        "COMPLETED",
        "DENIED",
        "CANCELLED",
        "EXPIRED",
        "FAILED",
        "BUSY",
        "UNKNOWN",
    ]
    status: str
    expires_at: float | None
    result: dict[str, Any] | None
    summary: str
    error_code: str | None
    job: JobResponse | None = None


class ActionEnvelope(StrictModel):
    result: ActionResponse


class JobEnvelope(StrictModel):
    result: JobResponse


class SessionCloseResponse(StrictModel):
    session_id: str
    generation: int
    state: Literal["CLOSED"]


class ContextEnvelope(StrictModel):
    context: ContextResponse


class ContextDeleteResponse(StrictModel):
    deleted: bool


class AgentEventResponse(StrictModel):
    sequence: int
    event_id: str
    event_type: str
    session_id: str | None
    action_id: str | None
    job_id: str | None
    payload: dict[str, Any]
    created_at: float


class AgentEventPollResponse(StrictModel):
    events: list[AgentEventResponse]
    next_after: int


class ProviderWebhookResponse(StrictModel):
    status: Literal["accepted"]
    disposition: str
    event_id: str
