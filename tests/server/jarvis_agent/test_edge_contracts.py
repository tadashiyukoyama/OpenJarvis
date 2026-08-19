from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from openjarvis.server.jarvis_agent.edge.auth import EdgeAuthenticator
from openjarvis.server.jarvis_agent.edge.config import EdgeCoreConfig
from openjarvis.server.jarvis_agent.edge.contract_export import schema_bundle
from openjarvis.server.jarvis_agent.edge.frames import (
    EdgeFrame,
    make_edge_frame,
    parse_edge_frame,
)
from openjarvis.server.jarvis_agent.edge.payloads import CLIENT_PAYLOADS, CORE_PAYLOADS


def _frame(frame_type: str, payload: dict, *, job_id: str | None = None) -> dict:
    return {
        "schema_version": "1.0",
        "event_id": str(uuid.uuid4()),
        "type": frame_type,
        "device_id": "workstation-1",
        "occurred_at": "2026-08-18T12:00:00Z",
        "sequence": 1,
        **({"job_id": job_id} if job_id else {}),
        "payload": payload,
    }


def test_edge_frame_accepts_closed_register_contract() -> None:
    value = _frame(
        "edge.register",
        {
            "worker_version": "1.0.0",
            "platform": "windows",
            "capabilities": ["codex.delegate"],
            "hostname_hash": "abc",
            "last_core_sequence": 0,
        },
    )
    parsed = parse_edge_frame(json.dumps(value), from_client=True)
    assert parsed.device_id == "workstation-1"
    assert parsed.validated_payload(from_client=True).model_dump()["capabilities"] == [
        "codex.delegate"
    ]


def test_edge_frame_rejects_unknown_payload_fields_and_missing_job_id() -> None:
    unknown = _frame(
        "edge.heartbeat",
        {"uptime_seconds": 1, "active_job_ids": [], "credential": "forbidden"},
    )
    with pytest.raises(ValidationError):
        parse_edge_frame(json.dumps(unknown), from_client=True)

    missing_job = _frame("job.accepted", {"attempt_id": "attempt-1"})
    with pytest.raises(ValidationError):
        parse_edge_frame(json.dumps(missing_job), from_client=True)


def test_edge_frame_rejects_wrong_direction_and_oversized_body() -> None:
    frame = _frame(
        "job.offer",
        {
            "attempt_id": "attempt-1",
            "tool_id": "codex.status",
            "arguments": {},
            "context": {"project_key": "", "codex_thread_id": "", "request_id": "r"},
            "payload_hash": "a" * 64,
            "lease_expires_at": "2026-08-18T12:01:00Z",
        },
        job_id="job-1",
    )
    with pytest.raises(ValueError, match="unsupported"):
        parse_edge_frame(json.dumps(frame), from_client=True)
    with pytest.raises(ValueError, match="size"):
        parse_edge_frame("{" + "x" * 100 + "}", from_client=True, max_bytes=10)


def test_codex_event_is_public_non_job_frame() -> None:
    value = _frame(
        "codex.event",
        {
            "event_schema_version": "1.0",
            "method": "turn/started",
            "thread_id": "thread-1",
            "turn_id": "turn-1",
            "event_type": "turn_started",
            "terminal_status": "RUNNING",
            "metadata": {},
        },
    )

    parsed = parse_edge_frame(json.dumps(value), from_client=True)
    assert parsed.job_id is None
    assert parsed.validated_payload(from_client=True).model_dump()["thread_id"] == (
        "thread-1"
    )
    value["job_id"] = "job-forbidden"
    with pytest.raises(ValidationError):
        parse_edge_frame(json.dumps(value), from_client=True)


def test_make_edge_frame_serializes_utc_and_validates_payload() -> None:
    frame = make_edge_frame(
        frame_type="edge.heartbeat_ack",
        device_id="workstation-1",
        sequence=2,
        payload={
            "acknowledged_sequence": 8,
            "server_time": "2026-08-18T12:00:00Z",
        },
        from_client=False,
        occurred_at=datetime(2026, 8, 18, 12, tzinfo=timezone.utc),
    )
    parsed = EdgeFrame.model_validate_json(frame.wire_json())
    assert parsed.sequence == 2


def test_edge_auth_supports_bounded_rotation_without_reusing_credentials() -> None:
    config = EdgeCoreConfig(
        device_id="workstation-1",
        token_current="current-secret",
        token_previous="previous-secret",
        token_previous_expires_at=200.0,
    )
    auth = EdgeAuthenticator(config)

    current = auth.authenticate(
        device_id="workstation-1",
        authorization="Bearer current-secret",
        now=100.0,
    )
    previous = auth.authenticate(
        device_id="workstation-1",
        authorization="Bearer previous-secret",
        now=100.0,
    )
    expired = auth.authenticate(
        device_id="workstation-1",
        authorization="Bearer previous-secret",
        now=201.0,
    )

    assert current and current.credential_slot == "current"
    assert previous and previous.credential_slot == "previous"
    assert expired is None
    assert (
        auth.authenticate(
            device_id="other", authorization="Bearer current-secret", now=100.0
        )
        is None
    )


def test_edge_core_environment_requires_strong_complete_credentials() -> None:
    with pytest.raises(ValueError, match="incomplete"):
        EdgeCoreConfig.from_env({"OPENJARVIS_EDGE_DEVICE_ID": "workstation-1"})

    with pytest.raises(ValueError, match="too short"):
        EdgeCoreConfig.from_env(
            {
                "OPENJARVIS_EDGE_DEVICE_ID": "workstation-1",
                "OPENJARVIS_EDGE_TOKEN_CURRENT": "short",
            }
        )

    with pytest.raises(ValueError, match="expiry"):
        EdgeCoreConfig.from_env(
            {
                "OPENJARVIS_EDGE_DEVICE_ID": "workstation-1",
                "OPENJARVIS_EDGE_TOKEN_CURRENT": "c" * 32,
                "OPENJARVIS_EDGE_TOKEN_PREVIOUS": "p" * 32,
            }
        )


def test_versioned_edge_fixtures_match_runtime_contract() -> None:
    fixtures = Path("contracts/edge/v1/fixtures")

    client = parse_edge_frame(
        (fixtures / "client-register.valid.json").read_text(encoding="utf-8"),
        from_client=True,
    )
    core = parse_edge_frame(
        (fixtures / "core-job-offer.valid.json").read_text(encoding="utf-8"),
        from_client=False,
    )
    codex_event = parse_edge_frame(
        (fixtures / "client-codex-event.valid.json").read_text(encoding="utf-8"),
        from_client=True,
    )

    assert client.type == "edge.register"
    assert core.type == "job.offer"
    assert codex_event.type == "codex.event"
    with pytest.raises(ValidationError):
        parse_edge_frame(
            (fixtures / "client-register.invalid.json").read_text(encoding="utf-8"),
            from_client=True,
        )


def test_versioned_edge_schemas_are_current() -> None:
    root = Path("contracts/edge/v1")
    expected = {
        "client-frames.schema.json": schema_bundle(
            CLIENT_PAYLOADS, direction="client-to-core"
        ),
        "core-frames.schema.json": schema_bundle(
            CORE_PAYLOADS, direction="core-to-client"
        ),
    }

    for name, schema in expected.items():
        persisted = json.loads((root / name).read_text(encoding="utf-8"))
        assert persisted == schema
