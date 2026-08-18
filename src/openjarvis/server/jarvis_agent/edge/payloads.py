"""Closed payload contracts for Edge protocol version 1.0."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class EdgePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RegisterPayload(EdgePayload):
    worker_version: str = Field(min_length=1, max_length=64)
    platform: str = Field(min_length=1, max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=64)
    hostname_hash: str = Field(default="", max_length=64)
    last_core_sequence: int = Field(default=0, ge=0)


class HeartbeatPayload(EdgePayload):
    uptime_seconds: int = Field(default=0, ge=0)
    active_job_ids: list[str] = Field(default_factory=list, max_length=64)


class ResumePayload(EdgePayload):
    last_core_sequence: int = Field(default=0, ge=0)
    active_job_ids: list[str] = Field(default_factory=list, max_length=64)


class JobAttemptPayload(EdgePayload):
    attempt_id: str = Field(min_length=1, max_length=160)


class JobRejectedPayload(JobAttemptPayload):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)


class JobProgressPayload(JobAttemptPayload):
    stage: str = Field(min_length=1, max_length=64)
    summary: str = Field(default="", max_length=1_000)
    progress_percent: int | None = Field(default=None, ge=0, le=100)


class ApprovalRequiredPayload(JobAttemptPayload):
    approval_id: str = Field(min_length=1, max_length=160)
    kind: Literal["command", "file_change", "permissions", "other"]
    preview: dict[str, Any]
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")


class JobSucceededPayload(JobAttemptPayload):
    status: str = Field(default="completed", min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=20_000)
    data: dict[str, Any] = Field(default_factory=dict)
    references: dict[str, str] = Field(default_factory=dict)


class JobFailedPayload(JobAttemptPayload):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=2_000)
    result_unknown: bool = False


class GoodbyePayload(EdgePayload):
    reason: str = Field(default="shutdown", min_length=1, max_length=128)


class RegisteredPayload(EdgePayload):
    connection_id: str = Field(min_length=1, max_length=160)
    heartbeat_interval_seconds: int = Field(ge=5, le=300)
    acknowledged_sequence: int = Field(ge=0)
    server_time: str = Field(min_length=1, max_length=64)


class HeartbeatAckPayload(EdgePayload):
    acknowledged_sequence: int = Field(ge=0)
    server_time: str = Field(min_length=1, max_length=64)


class JobOfferContext(EdgePayload):
    session_id: str = Field(min_length=1, max_length=160)
    partition_key: str = Field(min_length=1, max_length=256)
    project_key: str = Field(default="", max_length=1_024)
    codex_thread_id: str = Field(default="", max_length=256)
    request_id: str = Field(min_length=1, max_length=160)


class JobOfferPayload(EdgePayload):
    attempt_id: str = Field(min_length=1, max_length=160)
    tool_id: str = Field(min_length=1, max_length=128)
    arguments: dict[str, Any]
    context: JobOfferContext
    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    lease_expires_at: str = Field(min_length=1, max_length=64)


class JobCancelPayload(EdgePayload):
    attempt_id: str = Field(min_length=1, max_length=160)
    reason: str = Field(default="cancelled", min_length=1, max_length=256)


class ApprovalResolvedPayload(EdgePayload):
    attempt_id: str = Field(min_length=1, max_length=160)
    approval_id: str = Field(min_length=1, max_length=160)
    decision: Literal["approve", "deny"]


class RotateCredentialsPayload(EdgePayload):
    rotation_id: str = Field(min_length=1, max_length=160)
    effective_at: str = Field(min_length=1, max_length=64)
    credential_reference: str = Field(min_length=1, max_length=256)


class EdgeErrorPayload(EdgePayload):
    code: str = Field(min_length=1, max_length=64)
    message: str = Field(min_length=1, max_length=500)
    retryable: bool = False


CLIENT_PAYLOADS: dict[str, type[EdgePayload]] = {
    "edge.register": RegisterPayload,
    "edge.heartbeat": HeartbeatPayload,
    "edge.resume": ResumePayload,
    "job.accepted": JobAttemptPayload,
    "job.rejected": JobRejectedPayload,
    "job.progress": JobProgressPayload,
    "approval.required": ApprovalRequiredPayload,
    "job.succeeded": JobSucceededPayload,
    "job.failed": JobFailedPayload,
    "job.cancelled": JobAttemptPayload,
    "edge.goodbye": GoodbyePayload,
}

CORE_PAYLOADS: dict[str, type[EdgePayload]] = {
    "edge.registered": RegisteredPayload,
    "edge.heartbeat_ack": HeartbeatAckPayload,
    "job.offer": JobOfferPayload,
    "job.cancel": JobCancelPayload,
    "approval.resolved": ApprovalResolvedPayload,
    "edge.rotate_credentials": RotateCredentialsPayload,
    "edge.error": EdgeErrorPayload,
}


__all__ = [
    "CLIENT_PAYLOADS",
    "CORE_PAYLOADS",
    "ApprovalRequiredPayload",
    "ApprovalResolvedPayload",
    "EdgePayload",
    "JobOfferPayload",
    "JobSucceededPayload",
    "RegisterPayload",
]
