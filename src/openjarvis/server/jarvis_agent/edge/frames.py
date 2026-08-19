"""Versioned Edge frame envelope, validation and safe serialization."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from openjarvis.server.jarvis_agent.edge.payloads import (
    CLIENT_PAYLOADS,
    CORE_PAYLOADS,
    EdgePayload,
)

EDGE_SCHEMA_VERSION = "1.0"
MAX_EDGE_FRAME_BYTES = 256 * 1024

ClientFrameType = Literal[
    "edge.register",
    "edge.heartbeat",
    "edge.resume",
    "job.accepted",
    "job.rejected",
    "job.progress",
    "codex.event",
    "approval.required",
    "job.succeeded",
    "job.failed",
    "job.cancelled",
    "edge.goodbye",
]
CoreFrameType = Literal[
    "edge.registered",
    "edge.heartbeat_ack",
    "job.offer",
    "job.cancel",
    "approval.resolved",
    "edge.rotate_credentials",
    "edge.error",
]

_JOB_TYPES = frozenset(
    {
        "job.accepted",
        "job.rejected",
        "job.progress",
        "approval.required",
        "job.succeeded",
        "job.failed",
        "job.cancelled",
        "job.offer",
        "job.cancel",
        "approval.resolved",
    }
)


class EdgeFrame(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = EDGE_SCHEMA_VERSION
    event_id: uuid.UUID
    type: str = Field(min_length=1, max_length=64)
    device_id: str = Field(pattern=r"^[A-Za-z0-9._:-]{1,128}$")
    occurred_at: datetime
    sequence: int = Field(ge=1)
    job_id: str | None = Field(default=None, min_length=1, max_length=160)
    payload: dict[str, Any]

    @field_validator("occurred_at")
    @classmethod
    def require_utc_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_job_identity(self) -> "EdgeFrame":
        if self.type in _JOB_TYPES and not self.job_id:
            raise ValueError("job_id is required for job frames")
        if self.type not in _JOB_TYPES and self.job_id is not None:
            raise ValueError("job_id is forbidden for non-job frames")
        return self

    def validated_payload(self, *, from_client: bool) -> EdgePayload:
        contracts = CLIENT_PAYLOADS if from_client else CORE_PAYLOADS
        contract = contracts.get(self.type)
        if contract is None:
            raise ValueError("unsupported Edge frame type")
        return contract.model_validate(self.payload)

    def wire_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)

    def wire_json(self) -> str:
        return json.dumps(
            self.wire_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def parse_edge_frame(
    raw: str | bytes, *, from_client: bool, max_bytes: int = MAX_EDGE_FRAME_BYTES
) -> EdgeFrame:
    encoded = raw.encode("utf-8") if isinstance(raw, str) else raw
    if not encoded or len(encoded) > max_bytes:
        raise ValueError("Edge frame size is invalid")
    try:
        value = json.loads(encoded)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Edge frame is not valid JSON") from exc
    frame = EdgeFrame.model_validate(value)
    frame.validated_payload(from_client=from_client)
    return frame


def make_edge_frame(
    *,
    frame_type: str,
    device_id: str,
    sequence: int,
    payload: Mapping[str, Any],
    job_id: str | None = None,
    event_id: uuid.UUID | None = None,
    occurred_at: datetime | None = None,
    from_client: bool,
) -> EdgeFrame:
    frame = EdgeFrame(
        event_id=event_id or uuid.uuid4(),
        type=frame_type,
        device_id=device_id,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        sequence=sequence,
        job_id=job_id,
        payload=dict(payload),
    )
    frame.validated_payload(from_client=from_client)
    return frame


__all__ = [
    "CORE_PAYLOADS",
    "CLIENT_PAYLOADS",
    "EDGE_SCHEMA_VERSION",
    "MAX_EDGE_FRAME_BYTES",
    "EdgeFrame",
    "make_edge_frame",
    "parse_edge_frame",
]
