"""Explicit VPS-to-Edge dispatch for one existing Codex Desktop task."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.models import (
    ChatCompletionChunk,
    DeltaMessage,
    StreamChoice,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/codex", tags=["codex"])

_THREAD_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$")
_PUBLIC_CODES = frozenset(
    {
        "CODEX_BUSY",
        "CODEX_DISPATCH_TIMEOUT",
        "CODEX_THREAD_INVALID",
        "CODEX_THREAD_RESUME_TIMEOUT",
        "CODEX_THREAD_STATUS_TIMEOUT",
        "DEVICE_OFFLINE",
        "DUPLICATE_ACTION",
        "EDGE_JOB_TIMEOUT",
        "EXTERNAL_RESULT_UNKNOWN",
        "SESSION_CLOSED",
    }
)


class CodexTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    project_cwd: str = Field(min_length=3, max_length=1_024)
    message: str = Field(min_length=1, max_length=20_000)
    client_user_message_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")
    conversation_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,159}$")


def _error_code(exc: BaseException) -> str:
    if isinstance(exc, JarvisAgentError):
        return exc.code if exc.code in _PUBLIC_CODES else "EXTERNAL_RESULT_UNKNOWN"
    if isinstance(exc, sqlite3.IntegrityError):
        return "DUPLICATE_ACTION"
    value = str(exc).strip()
    return value if value in _PUBLIC_CODES else "EXTERNAL_RESULT_UNKNOWN"


def _chunk(chunk_id: str, content: str | None = None, *, finished: bool = False) -> str:
    chunk = ChatCompletionChunk(
        id=chunk_id,
        model="codex",
        choices=[
            StreamChoice(
                delta=DeltaMessage(content=content),
                finish_reason="stop" if finished else None,
            )
        ],
    )
    return f"data: {chunk.model_dump_json()}\n\n"


async def _stream_turn(
    runtime: Any,
    thread_id: str,
    payload: CodexTurnRequest,
) -> AsyncIterator[str]:
    chunk_id = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    started = json.dumps(
        {
            "thread_id": thread_id,
            "request_id": payload.client_user_message_id,
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    yield f"event: agent_turn_start\ndata: {started}\n\n"
    try:
        result = await asyncio.to_thread(
            runtime.start_turn,
            thread_id,
            project_cwd=payload.project_cwd,
            command=payload.message,
            request_id=payload.client_user_message_id,
            conversation_id=payload.conversation_id,
        )
        content = str(result.get("summary") or "").strip()
        if not content:
            raise RuntimeError("EXTERNAL_RESULT_UNKNOWN")
        yield _chunk(chunk_id, content)
        yield _chunk(chunk_id, finished=True)
    except Exception as exc:  # preserve one stable SSE error envelope
        code = _error_code(exc)
        logger.warning(
            "Codex Edge turn failed: code=%s thread_id=%s request_id=%s",
            code,
            thread_id,
            payload.client_user_message_id,
            exc_info=code == "EXTERNAL_RESULT_UNKNOWN",
        )
        error = json.dumps(
            {"code": code, "detail": code},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        yield f"event: error\ndata: {error}\n\n"
    yield "data: [DONE]\n\n"


@router.post("/threads/{thread_id}/turns")
async def start_codex_turn(
    thread_id: str,
    payload: CodexTurnRequest,
    request: Request,
) -> StreamingResponse:
    if not _THREAD_ID.fullmatch(thread_id):
        raise HTTPException(status_code=422, detail="Invalid Codex thread id")
    runtime = getattr(request.app.state, "codex_runtime", None)
    if runtime is None or not callable(getattr(runtime, "start_turn", None)):
        raise HTTPException(status_code=503, detail="Codex dispatch is not available")
    return StreamingResponse(
        _stream_turn(runtime, thread_id, payload),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


__all__ = ["CodexTurnRequest", "router"]
