"""Fail-closed relay for Codex app-server approval requests."""

from __future__ import annotations

import re
import threading
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from openjarvis.integrations.codex_protocol import JsonRpcServerRequest
from openjarvis.server.jarvis_agent.domain.models import payload_digest

_REDACT = re.compile(
    r"(?i)((?:authorization|api[_-]?key|token|secret|password)\s*[:=]\s*)[^\s,;]+"
)


@dataclass(slots=True)
class _PendingApproval:
    event: threading.Event
    decision: str | None = None


class CodexApprovalBridge:
    """Convert app-server callbacks into one visual Edge approval."""

    def __init__(
        self,
        send_required: Callable[[str, str, Mapping[str, Any]], None],
        *,
        timeout_seconds: float,
    ) -> None:
        self._send_required = send_required
        self._timeout_seconds = timeout_seconds
        self._lock = threading.RLock()
        self._pending: dict[str, _PendingApproval] = {}
        self._active_job: tuple[str, str] | None = None

    @contextmanager
    def activate(self, job_id: str, attempt_id: str) -> Iterator[None]:
        with self._lock:
            if self._active_job is not None:
                raise RuntimeError("another Codex approval context is active")
            self._active_job = (job_id, attempt_id)
        try:
            yield
        finally:
            with self._lock:
                self._active_job = None

    def handle(self, request: JsonRpcServerRequest) -> object:
        with self._lock:
            active = self._active_job
        if active is None:
            return self._denied_response(request.method)
        job_id, attempt_id = active
        approval_id = f"edgeapr_{uuid.uuid4().hex}"
        pending = _PendingApproval(threading.Event())
        with self._lock:
            self._pending[approval_id] = pending
        params = request.params if isinstance(request.params, Mapping) else {}
        preview = self._preview(request.method, params)
        digest = payload_digest(
            {"method": request.method, "params": self._hashable(params)}
        )
        try:
            self._send_required(
                job_id,
                "approval.required",
                {
                    "attempt_id": attempt_id,
                    "approval_id": approval_id,
                    "kind": self._kind(request.method),
                    "preview": preview,
                    "payload_hash": digest,
                },
            )
            if not pending.event.wait(self._timeout_seconds):
                return self._denied_response(request.method)
            return self._decision_response(request.method, params, pending.decision)
        finally:
            with self._lock:
                self._pending.pop(approval_id, None)

    def resolve(self, approval_id: str, decision: str) -> bool:
        with self._lock:
            pending = self._pending.get(approval_id)
            if pending is None or pending.event.is_set():
                return False
            pending.decision = decision
            pending.event.set()
            return True

    @staticmethod
    def _kind(method: str) -> str:
        if "permissions" in method:
            return "permissions"
        if "fileChange" in method or "applyPatch" in method:
            return "file_change"
        return "command"

    @classmethod
    def _preview(cls, method: str, params: Mapping[str, Any]) -> dict[str, Any]:
        preview: dict[str, Any] = {
            "destination": "Codex Desktop",
            "kind": cls._kind(method),
            "risk": "O Codex solicitou uma permissão local adicional.",
        }
        for source, target in (
            ("command", "command"),
            ("cwd", "cwd"),
            ("reason", "reason"),
            ("grantRoot", "path"),
        ):
            value = params.get(source)
            if isinstance(value, str) and value:
                preview[target] = _REDACT.sub(r"\1[REDACTED]", value)[:8_000]
            elif source == "command" and isinstance(value, list):
                command = " ".join(str(item) for item in value)
                preview[target] = _REDACT.sub(r"\1[REDACTED]", command)[:8_000]
        return preview

    @classmethod
    def _hashable(cls, value: Any) -> Any:
        if isinstance(value, Mapping):
            return {str(key): cls._hashable(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._hashable(item) for item in value]
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return repr(value)

    @staticmethod
    def _decision_response(
        method: str, params: Mapping[str, Any], decision: str | None
    ) -> object:
        approved = decision == "approve"
        if "permissions" in method:
            permissions = params.get("permissions") if approved else {}
            return {
                "permissions": permissions if isinstance(permissions, Mapping) else {},
                "scope": "turn",
            }
        return {"decision": "accept" if approved else "decline"}

    @classmethod
    def _denied_response(cls, method: str) -> object:
        return cls._decision_response(method, {}, "deny")


__all__ = ["CodexApprovalBridge"]
