"""Native OpenJarvis integration endpoints for the local Evolution API.

These routes are transport/status plumbing only.  The Agent Host remains the
single cognitive and outbound-policy authority; this router never sends a
WhatsApp message.  Instance creation is a separate owner-only route guarded by
an explicit provisioning flag.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from typing import Any, Mapping

from fastapi import APIRouter, HTTPException, Request, Response

from openjarvis.server.agent_host_bridge import _require_owner
from openjarvis.server.evolution_api import EvolutionApiClient

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/v1/integrations/whatsapp/evolution",
    tags=["whatsapp-evolution"],
)
_MAX_WEBHOOK_BYTES = 256 * 1024


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store, private, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


def _client(request: Request) -> EvolutionApiClient:
    current = getattr(request.app.state, "evolution_api_client", None)
    if isinstance(current, EvolutionApiClient):
        return current
    value = EvolutionApiClient()
    request.app.state.evolution_api_client = value
    return value


@router.get("/status")
def evolution_status(request: Request, response: Response) -> dict[str, Any]:
    """Return provider/instance state without returning any credential."""

    _require_owner(request)
    _no_store(response)
    return _client(request).status()


@router.get("/qr")
def evolution_qr(request: Request, response: Response) -> dict[str, Any]:
    """Return the current provider QR only to the authenticated owner UI."""

    _require_owner(request)
    _no_store(response)
    return _client(request).qr()


@router.post("/provision")
def evolution_provision(request: Request, response: Response) -> dict[str, Any]:
    """Create the named Evolution instance only when provisioning is enabled."""

    _require_owner(request)
    _no_store(response)
    return _client(request).provision()


def _webhook_secret(request: Request) -> str:
    configured = _client(request).config.webhook_secret
    supplied = request.headers.get("X-Evolution-Webhook-Secret", "").strip()
    if (
        len(configured) < 32
        or not supplied
        or not hmac.compare_digest(supplied, configured)
    ):
        raise HTTPException(
            status_code=403, detail="Evolution webhook authentication failed"
        )
    return configured


def _object(value: Any) -> Mapping[str, Any] | None:
    return value if isinstance(value, Mapping) else None


def _message_text(message: Mapping[str, Any]) -> str:
    for key in ("conversation", "text", "caption"):
        candidate = message.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    for key in (
        "extendedTextMessage",
        "imageMessage",
        "videoMessage",
        "documentMessage",
    ):
        nested = _object(message.get(key))
        if nested:
            for field in ("text", "caption", "contentText"):
                candidate = nested.get(field)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip()
    return ""


def _extract_inbound(payload: Mapping[str, Any]) -> dict[str, str] | None:
    event = str(payload.get("event") or payload.get("type") or "").lower()
    data = _object(payload.get("data")) or payload
    key = _object(data.get("key")) or {}
    jid = str(key.get("remoteJid") or data.get("remoteJid") or "").strip().lower()
    message_id = str(key.get("id") or data.get("id") or "").strip()
    if not jid or not message_id:
        return None
    if event and not any(
        marker in event for marker in ("message", "messages", "upsert")
    ):
        return None
    if bool(key.get("fromMe") or data.get("fromMe")):
        return None
    if jid.endswith("@g.us"):
        return {"blocked": "group_destination"}
    message = _object(data.get("message")) or {}
    text = _message_text(message)
    if not text:
        return {"ignored": "media_or_empty"}
    return {"jid": jid, "message_id": message_id, "text": text}


@router.post("/webhook", status_code=202)
async def evolution_webhook(request: Request) -> dict[str, Any]:
    """Authenticate one Evolution inbound event and wake the Agent Host.

    The provider JID never crosses into the Host.  Only an opaque conversation
    reference, principal and stable message id are forwarded.
    """

    _webhook_secret(request)
    body = await request.body()
    if len(body) > _MAX_WEBHOOK_BYTES:
        raise HTTPException(status_code=413, detail="Evolution webhook too large")
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=400, detail="Invalid Evolution webhook JSON"
        ) from exc
    if not isinstance(payload, Mapping):
        raise HTTPException(status_code=400, detail="Invalid Evolution webhook payload")
    inbound = _extract_inbound(payload)
    if inbound is None:
        return {"status": "ignored", "reason": "unsupported_event"}
    if inbound.get("blocked"):
        return {"status": "ignored", "reason": inbound["blocked"]}
    if inbound.get("ignored"):
        return {"status": "ignored", "reason": inbound["ignored"]}

    from openjarvis.server.whatsapp_agent_host import (
        AgentHostChannelClient,
        conversation_id_for_jid,
        principal_id_for_jid,
    )

    message_id = inbound["message_id"]
    conversation_id = conversation_id_for_jid(inbound["jid"])
    result = AgentHostChannelClient().submit(
        {
            "channel": "whatsapp_evolution",
            "principal_id": principal_id_for_jid(inbound["jid"]),
            "conversation_id": conversation_id,
            "message": inbound["text"],
            "message_id": message_id,
            "idempotency_key": f"wa-in:{message_id}",
            "correlation_id": hashlib.sha256(message_id.encode("utf-8")).hexdigest()[
                :32
            ],
        }
    )
    if result.get("status") not in {"accepted", "duplicate"}:
        logger.warning(
            "Evolution inbound rejected by Agent Host: %s", result.get("error")
        )
        raise HTTPException(status_code=503, detail="Agent Host unavailable")
    return {
        "status": result.get("status"),
        "event_id": result.get("event_id"),
        "message_id": message_id,
        "run_id": result.get("run_id"),
    }


__all__ = ["router"]
