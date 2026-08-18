"""Terminal Edge job transitions and public result mapping."""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.edge.frames import EdgeFrame
from openjarvis.server.jarvis_agent.edge.protocol import EdgeProtocol
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore

TERMINAL_EDGE_STATES = ("SUCCEEDED", "FAILED", "CANCELLED", "UNKNOWN")


class EdgeJobResults:
    def __init__(self, store: JarvisAgentStore, protocol: EdgeProtocol) -> None:
        self._store = store
        self._protocol = protocol

    def from_frame(
        self,
        assignment: Mapping[str, Any],
        frame: EdgeFrame,
        payload: Mapping[str, Any],
    ) -> dict[str, Any] | None:
        if frame.type == "job.succeeded":
            return self.finish(
                assignment,
                state="SUCCEEDED",
                event_id=str(frame.event_id),
                summary=str(payload["summary"]),
                result={
                    "status": payload["status"],
                    "summary": payload["summary"],
                    "data": payload["data"],
                    "references": payload["references"],
                },
            )
        if frame.type in {"job.rejected", "job.failed"}:
            unknown = frame.type == "job.failed" and payload["result_unknown"]
            return self.finish(
                assignment,
                state="UNKNOWN" if unknown else "FAILED",
                event_id=str(frame.event_id),
                summary=str(payload["message"]),
                error_code=self._protocol.safe_error_code(str(payload["code"])),
            )
        if frame.type == "job.cancelled":
            return self.finish(
                assignment,
                state="CANCELLED",
                event_id=str(frame.event_id),
                summary="O job Edge foi cancelado.",
                error_code="SESSION_CLOSED",
            )
        return None

    def finish(
        self,
        assignment: Mapping[str, Any],
        *,
        state: str,
        event_id: str,
        summary: str,
        error_code: str | None = None,
        result: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        updated = self._store.complete_edge_assignment(
            job_id=str(assignment["job_id"]),
            attempt_id=str(assignment["attempt_id"]),
            terminal_event_id=event_id,
            state=state,
            now=time.time(),
            result=result,
            summary=summary,
            error_code=error_code,
            sensitive_purge_at=time.time() + 86_400 if result else None,
        )
        return updated or dict(assignment)

    def existing(self, assignment: Mapping[str, Any]) -> dict[str, Any]:
        if assignment.get("state") in TERMINAL_EDGE_STATES:
            return self.result_or_raise(assignment)
        raise JarvisAgentError(
            "DUPLICATE_ACTION", "O job Edge já está em execução.", status_code=409
        )

    @staticmethod
    def result_or_raise(value: Mapping[str, Any]) -> dict[str, Any]:
        if value.get("state") == "SUCCEEDED":
            result = value.get("result")
            if isinstance(result, Mapping):
                return dict(result)
            return {
                "status": "completed",
                "summary": str(value.get("result_summary") or "Concluído."),
                "data": {},
                "references": {},
            }
        raise EdgeJobResults.terminal_error(value)

    @staticmethod
    def terminal_error(value: Mapping[str, Any]) -> JarvisAgentError:
        code = EdgeProtocol.safe_error_code(str(value.get("error_code") or ""))
        return JarvisAgentError(
            code,
            str(value.get("result_summary") or "O job Edge falhou."),
            status_code=504
            if code in {"EDGE_JOB_TIMEOUT", "CODEX_DISPATCH_TIMEOUT"}
            else 502,
        )


__all__ = ["EdgeJobResults", "TERMINAL_EDGE_STATES"]
