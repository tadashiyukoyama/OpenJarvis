"""Thin FastAPI routes for the server-side Jarvis agent orchestrator."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from openjarvis.server.jarvis_agent.api.container import get_orchestrator
from openjarvis.server.jarvis_agent.api.events import event_stream
from openjarvis.server.jarvis_agent.api.schemas import (
    ActionDecision,
    ActionEnvelope,
    AgentEventPollResponse,
    CatalogResponse,
    ContextDelete,
    ContextDeleteResponse,
    ContextEnvelope,
    JobEnvelope,
    ProposalCreate,
    ProviderWebhookResponse,
    SessionClose,
    SessionCloseResponse,
    SessionCreate,
    SessionResponse,
    TurnCreate,
    TurnResponse,
)
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.services.presentation import (
    public_action,
    public_job,
)

router = APIRouter(prefix="/v1/jarvis/agent", tags=["jarvis-agent"])
_MAX_ACELERACHAT_WEBHOOK_BYTES = 1024 * 1024


async def _read_acelerachat_webhook_body(request: Request) -> bytes:
    declared = request.headers.get("content-length")
    if declared:
        try:
            declared_size = int(declared)
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail={
                    "code": "WEBHOOK_INVALID_PAYLOAD",
                    "message": "Content-Length do webhook é inválido.",
                },
            ) from exc
        if declared_size < 0 or declared_size > _MAX_ACELERACHAT_WEBHOOK_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "WEBHOOK_INVALID_PAYLOAD",
                    "message": "Webhook excedeu o limite seguro.",
                },
            )
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > _MAX_ACELERACHAT_WEBHOOK_BYTES:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "WEBHOOK_INVALID_PAYLOAD",
                    "message": "Webhook excedeu o limite seguro.",
                },
            )
        body.extend(chunk)
    return bytes(body)


def _http_error(exc: JarvisAgentError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.as_dict())


async def _run(function: Any, /, *args: Any, **kwargs: Any) -> Any:
    try:
        return await asyncio.to_thread(function, *args, **kwargs)
    except JarvisAgentError as exc:
        raise _http_error(exc) from exc


@router.get("/catalog", response_model=CatalogResponse)
async def catalog(request: Request) -> dict[str, Any]:
    return await _run(get_orchestrator(request.app).catalog_snapshot)


@router.post("/sessions", status_code=201, response_model=SessionResponse)
async def create_session(payload: SessionCreate, request: Request) -> dict[str, Any]:
    return await _run(
        get_orchestrator(request.app).create_session,
        project_key=payload.project_key,
        codex_thread_id=payload.codex_thread_id,
    )


@router.post(
    "/sessions/{session_id}/turns", status_code=201, response_model=TurnResponse
)
async def commit_turn(
    session_id: str, payload: TurnCreate, request: Request
) -> dict[str, Any]:
    return await _run(
        get_orchestrator(request.app).commit_turn,
        session_id=session_id,
        generation=payload.generation,
        turn_id=payload.turn_id,
        transcript=payload.transcript,
    )


@router.post("/sessions/{session_id}/proposals", response_model=ActionEnvelope)
async def create_proposal(
    session_id: str, payload: ProposalCreate, request: Request
) -> dict[str, Any]:
    result = await _run(
        get_orchestrator(request.app).propose,
        session_id=session_id,
        generation=payload.generation,
        function_call_id=payload.function_call_id,
        tool_name=payload.name,
        arguments=payload.arguments,
        turn_id=payload.turn_id,
    )
    return {"result": result}


@router.post("/actions/{action_id}/decision", response_model=ActionEnvelope)
async def decide_action(
    action_id: str,
    payload: ActionDecision,
    request: Request,
    decision_channel: str = Header(default="", alias="X-Jarvis-Decision-Channel"),
) -> dict[str, Any]:
    if decision_channel != "visual":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "APPROVAL_REQUIRED",
                "message": "A decisão exige o controle visual do Jarvis.",
            },
        )
    result = await _run(
        get_orchestrator(request.app).decide,
        action_id=action_id,
        session_id=payload.session_id,
        payload_hash=payload.payload_hash,
        decision=payload.decision,
    )
    return {"result": result}


@router.get("/actions/{action_id}", response_model=ActionEnvelope)
async def get_action(action_id: str, request: Request) -> dict[str, Any]:
    orchestrator = get_orchestrator(request.app)
    await asyncio.to_thread(orchestrator.store.expire)
    action = await asyncio.to_thread(orchestrator.store.get_action, action_id)
    if action is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "ACTION_NOT_FOUND", "message": "A ação não existe."},
        )
    return {"result": public_action(action)}


@router.get("/jobs/{job_id}", response_model=JobEnvelope)
async def get_job(job_id: str, request: Request) -> dict[str, Any]:
    orchestrator = get_orchestrator(request.app)
    job = await asyncio.to_thread(orchestrator.store.get_job, job_id)
    if job is None:
        raise HTTPException(
            status_code=404,
            detail={"code": "JOB_NOT_FOUND", "message": "O trabalho não existe."},
        )
    return {"result": public_job(job)}


@router.get("/events")
async def events(
    request: Request, after: int = Query(default=0, ge=0)
) -> StreamingResponse:
    orchestrator = get_orchestrator(request.app)
    last_id = request.headers.get("last-event-id", "").strip()
    if last_id.isdigit():
        after = max(after, int(last_id))
    return StreamingResponse(
        event_stream(request, orchestrator.events, after=after),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )


@router.get("/events/poll", response_model=AgentEventPollResponse)
async def poll_events(
    request: Request,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Return a finite event page for transports that cannot carry SSE."""

    orchestrator = get_orchestrator(request.app)
    values = await asyncio.to_thread(orchestrator.events.after, after, limit)
    next_after = max((int(item["sequence"]) for item in values), default=after)
    return {"events": values, "next_after": next_after}


@router.get("/events/history", response_model=AgentEventPollResponse)
async def thread_event_history(
    request: Request,
    project_key: str = Query(min_length=1, max_length=1024),
    codex_thread_id: str = Query(min_length=1, max_length=256),
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, Any]:
    """Return durable Agent Core events for one selected Codex target."""

    orchestrator = get_orchestrator(request.app)
    values = await asyncio.to_thread(
        orchestrator.store.list_thread_events,
        project_key,
        codex_thread_id,
        limit,
    )
    next_after = max((int(item["sequence"]) for item in values), default=0)
    return {"events": values, "next_after": next_after}


@router.post(
    "/providers/acelerachat/webhooks",
    status_code=202,
    response_model=ProviderWebhookResponse,
)
async def acelerachat_webhook(
    request: Request,
    delivery_id: str = Header(default="", alias="X-AceleraChat-Delivery"),
    timestamp: str = Header(default="", alias="X-AceleraChat-Timestamp"),
    signature: str = Header(default="", alias="X-AceleraChat-Signature"),
    previous_signature: str = Header(
        default="", alias="X-AceleraChat-Signature-Previous"
    ),
) -> dict[str, Any]:
    service = get_orchestrator(request.app).acelerachat_webhooks
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "SOURCE_DISCONNECTED",
                "message": "O adaptador AceleraChat não está ativo.",
            },
        )
    body = await _read_acelerachat_webhook_body(request)
    return await _run(
        service.receive,
        body,
        delivery_id=delivery_id,
        timestamp=timestamp,
        signature=signature,
        previous_signature=previous_signature,
    )


@router.post("/sessions/{session_id}/close", response_model=SessionCloseResponse)
async def close_session(
    session_id: str, payload: SessionClose, request: Request
) -> dict[str, Any]:
    return await _run(
        get_orchestrator(request.app).close_session,
        session_id,
        payload.generation,
    )


@router.get("/context", response_model=ContextEnvelope)
async def get_context(
    request: Request,
    project_key: str = Query(min_length=1, max_length=1024),
    codex_thread_id: str = Query(default="", max_length=256),
) -> dict[str, Any]:
    context = await _run(
        get_orchestrator(request.app).context.read, project_key, codex_thread_id
    )
    return {"context": context}


@router.delete("/context", response_model=ContextDeleteResponse)
async def delete_context(payload: ContextDelete, request: Request) -> dict[str, Any]:
    deleted = await _run(
        get_orchestrator(request.app).context.delete,
        payload.project_key,
        payload.codex_thread_id,
    )
    return {"deleted": bool(deleted)}
