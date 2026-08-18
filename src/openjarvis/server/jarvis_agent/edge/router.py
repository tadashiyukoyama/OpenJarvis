"""Authenticated Edge WebSocket and management endpoints."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request, WebSocket
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.websockets import WebSocketDisconnect

from openjarvis.server.jarvis_agent.api.container import get_orchestrator
from openjarvis.server.jarvis_agent.domain.errors import JarvisAgentError
from openjarvis.server.jarvis_agent.edge.auth import EdgeAuthenticator
from openjarvis.server.jarvis_agent.edge.connection import EdgeConnection
from openjarvis.server.jarvis_agent.edge.frames import EdgeFrame, parse_edge_frame

logger = logging.getLogger(__name__)
router = APIRouter(tags=["jarvis-edge"])


class EdgeApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payload_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    decision: Literal["approve", "deny"]


def _error(exc: JarvisAgentError) -> HTTPException:
    return HTTPException(status_code=exc.status_code, detail=exc.as_dict())


@router.get("/v1/jarvis/agent/edge/status")
async def edge_status(request: Request) -> dict[str, Any]:
    return get_orchestrator(request.app).edge.status()


@router.post("/v1/jarvis/agent/edge/approvals/{approval_id}/decision")
async def decide_edge_approval(
    approval_id: str,
    payload: EdgeApprovalDecision,
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
    try:
        result = await asyncio.to_thread(
            get_orchestrator(request.app).edge.decide_approval,
            approval_id=approval_id,
            payload_hash=payload.payload_hash,
            decision=payload.decision,
        )
    except JarvisAgentError as exc:
        raise _error(exc) from exc
    return {"result": result}


@router.post("/v1/jarvis/agent/edge/devices/{device_id}/revoke")
async def revoke_edge_device(
    device_id: str,
    request: Request,
    decision_channel: str = Header(default="", alias="X-Jarvis-Decision-Channel"),
) -> dict[str, Any]:
    if decision_channel != "visual":
        raise HTTPException(
            status_code=403,
            detail={
                "code": "APPROVAL_REQUIRED",
                "message": "A revogação exige confirmação visual autenticada.",
            },
        )
    revoked = await get_orchestrator(request.app).edge.revoke_device(device_id)
    if not revoked:
        raise HTTPException(
            status_code=404,
            detail={"code": "DEVICE_OFFLINE", "message": "Dispositivo desconhecido."},
        )
    return {"device_id": device_id, "state": "REVOKED"}


@router.websocket("/edge")
async def edge_websocket(websocket: WebSocket) -> None:
    service = get_orchestrator(websocket.app).edge
    identity = EdgeAuthenticator(service.config).authenticate(
        device_id=websocket.headers.get("x-openjarvis-device-id", "").strip(),
        authorization=websocket.headers.get("authorization", ""),
    )
    if identity is None:
        await websocket.close(code=4401, reason="unauthorized")
        return
    await websocket.accept()
    connection: EdgeConnection | None = None
    error_code: str | None = None
    try:
        first = await _receive_frame(
            websocket,
            timeout=service.config.offer_accept_timeout_seconds,
            max_bytes=service.config.max_frame_bytes,
        )
        connection = await service.register(
            websocket=websocket,
            credential_slot=identity.credential_slot,
            frame=first,
        )
        while True:
            frame = await _receive_frame(
                websocket,
                timeout=service.config.heartbeat_timeout_seconds,
                max_bytes=service.config.max_frame_bytes,
            )
            if not await service.handle(connection, frame):
                break
    except asyncio.TimeoutError:
        error_code = "EDGE_JOB_TIMEOUT"
        await websocket.close(code=4408, reason="heartbeat_timeout")
    except WebSocketDisconnect:
        error_code = "DEVICE_OFFLINE"
    except (ValueError, ValidationError) as exc:
        error_code = "EDGE_FRAME_INVALID"
        logger.info("Rejected invalid Edge frame: %s", type(exc).__name__)
        await websocket.close(code=4400, reason="invalid_frame")
    except JarvisAgentError as exc:
        error_code = exc.code
        logger.info("Edge protocol rejected event: %s", exc.code)
        await websocket.close(code=4409, reason=exc.code.lower()[:100])
    except Exception:
        error_code = "EXTERNAL_RESULT_UNKNOWN"
        logger.exception("Unexpected Edge WebSocket failure")
        await websocket.close(code=1011, reason="internal_error")
    finally:
        if connection is not None:
            service.unregister(connection, error_code=error_code)


async def _receive_frame(
    websocket: WebSocket, *, timeout: float, max_bytes: int
) -> EdgeFrame:
    raw = await asyncio.wait_for(websocket.receive_text(), timeout=timeout)
    return parse_edge_frame(raw, from_client=True, max_bytes=max_bytes)


__all__ = ["router"]
