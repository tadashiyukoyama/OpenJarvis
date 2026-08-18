"""Safe public projections for persisted Jarvis agent records."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def public_action(action: Mapping[str, Any]) -> dict[str, Any]:
    state = str(action.get("state") or "")
    status = {
        "AWAITING_APPROVAL": "approval_required",
        "ACCEPTED": "accepted",
        "COMPLETED": "completed",
        "DENIED": "denied",
        "EXPIRED": "expired",
        "BUSY": "busy",
        "UNKNOWN": "unknown",
        "FAILED": "failed",
        "DISPATCHING": "dispatching",
    }.get(state, state.lower())
    return {
        "action_id": action.get("action_id"),
        "session_id": action.get("session_id"),
        "function_call_id": action.get("function_call_id"),
        "tool_id": action.get("tool_id"),
        "payload_hash": action.get("payload_hash"),
        "preview": dict(action.get("preview") or {}),
        "state": state,
        "status": status,
        "expires_at": action.get("expires_at"),
        "result": action.get("result"),
        "summary": action.get("result_summary") or "",
        "error_code": action.get("error_code"),
    }


def public_job(job: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "job_id": job.get("job_id"),
        "action_id": job.get("action_id"),
        "state": job.get("state"),
        "result": job.get("result"),
        "summary": job.get("result_summary") or "",
        "error_code": job.get("error_code"),
        "updated_at": job.get("updated_at"),
    }
