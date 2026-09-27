"""Authenticated, thin HTTP bridge to the local Agent Host.

OpenJarvis is the owner-facing transport/UI.  The Agent Host remains the
source of truth for the Codex session, queue, policy and approvals.  This
module deliberately contains no tool catalog or decision logic.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/agent-host", tags=["agent-host"])


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OwnerMessage(_StrictModel):
    conversation_id: str = Field(min_length=1, max_length=256)
    message: str = Field(min_length=1, max_length=20_000)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=128)


class OperatorWhatsAppReply(_StrictModel):
    """Explicit owner intervention in an existing opaque WhatsApp thread."""

    conversation_id: str = Field(
        min_length=35, max_length=35, pattern=r"^wa:[0-9a-f]{32}$"
    )
    message: str = Field(min_length=1, max_length=4_000)
    idempotency_key: str = Field(min_length=1, max_length=256)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=160)
    confirm_send: bool = False


class HostControl(_StrictModel):
    command: str = Field(min_length=1, max_length=32)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)


class ApprovalRequest(_StrictModel):
    preview: dict[str, Any] = Field(default_factory=lambda: {"kind": "safe_test"})
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)


class ApprovalDecision(_StrictModel):
    decision: str = Field(min_length=1, max_length=16)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=256)


class GatewayWhatsAppSend(_StrictModel):
    conversation_id: str = Field(
        min_length=35, max_length=35, pattern=r"^wa:[0-9a-f]{32}$"
    )
    text: str = Field(min_length=1, max_length=4_000)
    idempotency_key: str = Field(min_length=1, max_length=200)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=160)
    execution_context: dict[str, Any] = Field(default_factory=dict)


class GatewayWhatsAppMedia(_StrictModel):
    conversation_id: str = Field(
        min_length=35, max_length=35, pattern=r"^wa:[0-9a-f]{32}$"
    )
    artifact_id: str = Field(
        min_length=40, max_length=45, pattern=r"^art-[0-9a-f-]{36}$"
    )
    artifact_path: str = Field(min_length=1, max_length=1024)
    filename: str = Field(min_length=1, max_length=120)
    mime_type: str = Field(min_length=1, max_length=80)
    size: int = Field(ge=1, le=12 * 1024 * 1024)
    sha256: str = Field(min_length=64, max_length=64, pattern=r"^[0-9a-f]{64}$")
    caption: str = Field(default="", max_length=4000)
    voice_note: bool = False
    idempotency_key: str = Field(min_length=1, max_length=200)
    correlation_id: str | None = Field(default=None, min_length=1, max_length=160)
    execution_context: dict[str, Any] = Field(default_factory=dict)


def _loopback(request: Request) -> bool:
    client = request.client.host if request.client else ""
    return client in {"127.0.0.1", "::1", "localhost", "testclient"}


def _require_owner(request: Request) -> None:
    """Map the authenticated local UI to the only supported principal: owner.

    A configured OpenJarvis API key is the normal owner authentication.  A
    keyless server is intentionally restricted to loopback, which is the
    documented local-only mode; remote binding requires the existing API-key
    middleware before this route is reachable.
    """

    api_key = str(getattr(request.app.state, "api_key", "") or "")
    if api_key:
        authorization = request.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or not hmac.compare_digest(token, api_key):
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "OWNER_AUTH_REQUIRED",
                    "message": "Owner authentication required.",
                },
            )
        return
    if not _loopback(request):
        raise HTTPException(
            status_code=401,
            detail={
                "code": "OWNER_AUTH_REQUIRED",
                "message": "Loopback owner session required.",
            },
        )


class AgentHostClient:
    def __init__(self) -> None:
        self.base_url = os.environ.get(
            "OPENJARVIS_AGENT_HOST_URL", "http://127.0.0.1:8765"
        ).rstrip("/")
        self.shared_secret = os.environ.get("AGENT_HOST_SHARED_SECRET", "")
        self.timeout = httpx.Timeout(15.0, connect=3.0)

    def _headers(self, method: str, path: str, body: bytes) -> dict[str, str]:
        if len(self.shared_secret) < 32:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "AGENT_HOST_AUTH_UNCONFIGURED",
                    "message": "Agent Host service authentication is not configured.",
                },
            )
        timestamp = str(int(time.time()))
        canonical = "\n".join(
            (timestamp, method.upper(), path, hashlib.sha256(body).hexdigest())
        ).encode("utf-8")
        signature = hmac.new(
            self.shared_secret.encode("utf-8"), canonical, hashlib.sha256
        ).hexdigest()
        return {
            "X-Agent-Principal": "owner",
            "X-Agent-Timestamp": timestamp,
            "X-Agent-Signature": signature,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    async def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        query: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        body = (
            b""
            if payload is None
            else json.dumps(
                payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )
        headers = self._headers(method, path, body)
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method,
                    self.base_url + path,
                    params=query,
                    content=body or None,
                    headers=headers,
                )
        except httpx.TimeoutException as exc:
            raise HTTPException(
                status_code=504,
                detail={
                    "code": "AGENT_HOST_TIMEOUT",
                    "message": "Agent Host did not respond in time.",
                },
            ) from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "AGENT_HOST_UNAVAILABLE",
                    "message": "Agent Host is unavailable.",
                },
            ) from exc
        try:
            data = response.json()
        except ValueError:
            data = {"error": "AGENT_HOST_INVALID_RESPONSE"}
        if response.status_code >= 400:
            detail = data if isinstance(data, dict) else {"error": "AGENT_HOST_ERROR"}
            raise HTTPException(status_code=response.status_code, detail=detail)
        return data if isinstance(data, dict) else {"result": data}


def _client(request: Request) -> AgentHostClient:
    existing = getattr(request.app.state, "agent_host_client", None)
    if isinstance(existing, AgentHostClient):
        return existing
    value = AgentHostClient()
    request.app.state.agent_host_client = value
    return value


def _require_gateway_signature(request: Request, body: bytes) -> None:
    """Authenticate only the loopback Agent Host -> provider gateway call."""

    if not _loopback(request):
        raise HTTPException(status_code=401, detail="Gateway loopback required")
    principal = request.headers.get("X-Agent-Principal", "")
    if principal != "agent-host-gateway":
        raise HTTPException(status_code=401, detail="Gateway principal invalid")
    secret = os.environ.get("AGENT_HOST_SHARED_SECRET", "")
    if len(secret) < 32:
        raise HTTPException(
            status_code=503, detail="Gateway authentication unconfigured"
        )
    timestamp = request.headers.get("X-Agent-Timestamp", "")
    try:
        parsed = int(timestamp)
    except ValueError as exc:
        raise HTTPException(
            status_code=401, detail="Gateway timestamp invalid"
        ) from exc
    if abs(int(time.time()) - parsed) > 120:
        raise HTTPException(status_code=401, detail="Gateway timestamp expired")
    path = request.url.path
    canonical = "\n".join(
        (str(parsed), request.method.upper(), path, hashlib.sha256(body).hexdigest())
    ).encode("utf-8")
    expected = hmac.new(secret.encode("utf-8"), canonical, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get("X-Agent-Signature", ""), expected):
        raise HTTPException(status_code=401, detail="Gateway signature invalid")


@router.get("/status")
async def status(request: Request, conversation_id: str = "") -> dict[str, Any]:
    _require_owner(request)
    return await _client(request).request(
        "GET", "/v1/agent-host/status", query={"conversation_id": conversation_id}
    )


@router.get("/history")
async def history(
    request: Request, conversation_id: str, after: int = 0
) -> dict[str, Any]:
    _require_owner(request)
    return await _client(request).request(
        "GET",
        "/v1/agent-host/history",
        query={"conversation_id": conversation_id, "after": str(max(0, after))},
    )


@router.get("/whatsapp/conversations")
async def whatsapp_conversations(request: Request, limit: int = 100) -> dict[str, Any]:
    """List safe, opaque WhatsApp conversation summaries for the owner UI."""

    _require_owner(request)
    bounded = min(100, max(1, int(limit)))
    return await _client(request).request(
        "GET", "/v1/agent-host/conversations", query={"limit": str(bounded)}
    )


@router.get("/events")
async def events(
    request: Request, conversation_id: str, after: int = 0
) -> dict[str, Any]:
    _require_owner(request)
    return await _client(request).request(
        "GET",
        "/v1/agent-host/events",
        query={"conversation_id": conversation_id, "after": str(max(0, after))},
    )


@router.get("/artifacts")
async def artifacts(request: Request, conversation_id: str = "") -> dict[str, Any]:
    """List safe artifact metadata for the selected Agent Host conversation."""

    _require_owner(request)
    return await _client(request).request(
        "GET", "/v1/agent-host/artifacts", query={"conversation_id": conversation_id}
    )


@router.post("/messages", status_code=202)
async def message(payload: OwnerMessage, request: Request) -> dict[str, Any]:
    _require_owner(request)
    # The gateway signs the canonical five-field JSON payload, including a
    # null correlation_id when it was omitted by the caller.
    body = payload.model_dump()
    body["principal_id"] = "owner"
    return await _client(request).request("POST", "/v1/agent-host/messages", body)


@router.post("/whatsapp/reply")
async def whatsapp_operator_reply(
    payload: OperatorWhatsAppReply, request: Request
) -> dict[str, Any]:
    """Send one confirmed human reply through the existing Agent Host gateway."""

    _require_owner(request)
    if not payload.confirm_send:
        raise HTTPException(
            status_code=409, detail="Explicit send confirmation is required"
        )
    return await _client(request).request(
        "POST", "/v1/agent-host/whatsapp/reply", payload.model_dump(exclude_none=True)
    )


@router.post("/control", status_code=202)
async def control(payload: HostControl, request: Request) -> dict[str, Any]:
    _require_owner(request)
    return await _client(request).request(
        "POST", "/v1/agent-host/control", payload.model_dump()
    )


@router.post("/approvals/test", status_code=202)
async def approval_test(payload: ApprovalRequest, request: Request) -> dict[str, Any]:
    _require_owner(request)
    return await _client(request).request(
        "POST", "/v1/agent-host/approvals/test", payload.model_dump()
    )


@router.post("/approvals/{approval_id}/decision", status_code=202)
async def approval_decision(
    approval_id: str, payload: ApprovalDecision, request: Request
) -> dict[str, Any]:
    _require_owner(request)
    return await _client(request).request(
        "POST", f"/v1/agent-host/approvals/{approval_id}/decision", payload.model_dump()
    )


@router.post("/gateway/whatsapp/send")
async def gateway_whatsapp_send(
    payload: GatewayWhatsAppSend, request: Request
) -> dict[str, Any]:
    body = payload.model_dump(exclude_none=True)
    _require_gateway_signature(
        request,
        json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8"),
    )
    try:
        from openjarvis.server.jarvis_sources_router import _whatsapp
        from openjarvis.server.whatsapp_agent_host import (
            configure_whatsapp_agent_host,
            get_whatsapp_agent_host_gateway,
        )

        gateway = get_whatsapp_agent_host_gateway(request.app)
        if gateway is None:
            channel = _whatsapp(request)
            gateway = configure_whatsapp_agent_host(request.app, channel)
        return gateway.send_message(body, payload.execution_context)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="WhatsApp gateway unavailable"
        ) from exc


@router.post("/gateway/whatsapp/media")
async def gateway_whatsapp_media(
    payload: GatewayWhatsAppMedia, request: Request
) -> dict[str, Any]:
    body = payload.model_dump(exclude_none=True)
    _require_gateway_signature(
        request,
        json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8"),
    )
    try:
        from openjarvis.server.jarvis_sources_router import _whatsapp
        from openjarvis.server.whatsapp_agent_host import (
            configure_whatsapp_agent_host,
            get_whatsapp_agent_host_gateway,
        )

        gateway = get_whatsapp_agent_host_gateway(request.app)
        if gateway is None:
            channel = _whatsapp(request)
            gateway = configure_whatsapp_agent_host(request.app, channel)
        return gateway.send_media(body, payload.execution_context)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="WhatsApp gateway unavailable"
        ) from exc


@router.get("/gateway/whatsapp/operation")
async def gateway_whatsapp_operation(
    request: Request,
    operation_id: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Read one durable outbound result for safe post-unknown recovery.

    This route is deliberately not a send/replay endpoint.  It only reads the
    provider's durable idempotency index and returns ``not_found`` when the
    provider cannot prove what happened.
    """

    operation = str(operation_id or "").strip()
    idem = str(idempotency_key or "").strip()
    if bool(operation) == bool(idem):
        raise HTTPException(
            status_code=422,
            detail="exactly one of operation_id or idempotency_key is required",
        )
    _require_gateway_signature(request, b"")
    try:
        from openjarvis.server.whatsapp_agent_host import (
            get_whatsapp_agent_host_gateway,
        )

        gateway = get_whatsapp_agent_host_gateway(request.app)
        if gateway is None:
            raise HTTPException(
                status_code=503, detail="WhatsApp outbound store unavailable"
            )
        result = gateway.get_outbound_operation(
            operation_id=operation or None,
            idempotency_key=idem or None,
        )
        result = dict(result)
        result.setdefault("status", "unknown")
        return result
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="WhatsApp outbound store unavailable"
        ) from exc


__all__ = ["AgentHostClient", "router"]
