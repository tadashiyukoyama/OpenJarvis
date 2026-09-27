"""Baileys <-> Agent Host transport boundary.

This module is deliberately a channel adapter, not an agent.  Baileys owns
the provider session and its local SQLite index; the Agent Host owns the Codex
run, policy, idempotency and tool dispatch.  Only opaque conversation
references cross the boundary, so raw WhatsApp JIDs never enter Host history
or the Codex prompt.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from openjarvis.channels._stubs import ChannelMessage
from openjarvis.channels.whatsapp.identity import classify_jid

logger = logging.getLogger(__name__)

_CONVERSATION_RE = re.compile(r"^wa:[0-9a-f]{32}$")
_PRINCIPAL_RE = re.compile(r"^[a-z][a-z0-9._:-]{0,127}$")
_GATEWAY_PATH = "/v1/agent-host/gateway/whatsapp/send"
_MEDIA_GATEWAY_PATH = "/v1/agent-host/gateway/whatsapp/media"


def _json_bytes(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _secret() -> bytes:
    value = os.environ.get("OPENJARVIS_WHATSAPP_ID_SECRET", "").strip()
    if not value:
        value = os.environ.get("AGENT_HOST_SHARED_SECRET", "").strip()
    return value.encode("utf-8")


def _jid(value: Any) -> str:
    value = str(value or "").strip().lower()
    if "@" in value:
        local, domain = value.split("@", 1)
        # Baileys may report the authenticated account with a device suffix
        # (number:device@s.whatsapp.net), while remote messages use the PN.
        if domain == "s.whatsapp.net" and ":" in local:
            local = local.split(":", 1)[0]
        value = f"{local}@{domain}"
    return value


def _opaque(prefix: str, value: str) -> str:
    secret = _secret()
    digest = (
        hmac.new(secret, value.encode("utf-8"), hashlib.sha256).hexdigest()
        if secret
        else hashlib.sha256(value.encode("utf-8")).hexdigest()
    )
    return f"{prefix}:{digest[:32]}"


def conversation_id_for_jid(jid: str) -> str:
    """Return a stable reference with no reversible phone/JID material."""

    return _opaque("wa", _jid(jid))


def principal_id_for_jid(jid: str) -> str:
    candidate = _jid(jid)
    owner = _jid(os.environ.get("OPENJARVIS_WHATSAPP_OWNER_JID", ""))
    if owner and hmac.compare_digest(candidate, owner):
        return "owner"
    return _opaque("whatsapp", candidate)


def _allowed_jids() -> set[str]:
    values = {
        _jid(item)
        for item in os.environ.get("OPENJARVIS_WHATSAPP_ALLOWED_JIDS", "").split(",")
        if _jid(item)
    }
    owner = _jid(os.environ.get("OPENJARVIS_WHATSAPP_OWNER_JID", ""))
    if owner:
        values.add(owner)
    return values


def _path_has_symlink(path: Path) -> bool:
    """Check every path component before resolving a provider path."""

    current = path.absolute()
    while True:
        if current.is_symlink():
            return True
        parent = current.parent
        if parent == current:
            return False
        current = parent


class AgentHostChannelClient:
    """Authenticated, synchronous ingress client used by the reader thread."""

    def __init__(self) -> None:
        self.base_url = os.environ.get(
            "OPENJARVIS_AGENT_HOST_URL", "http://127.0.0.1:8765"
        ).rstrip("/")
        self.shared_secret = os.environ.get("AGENT_HOST_SHARED_SECRET", "")
        self.timeout_seconds = float(
            os.environ.get("OPENJARVIS_AGENT_HOST_CHANNEL_TIMEOUT", "5")
        )

    def submit(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        body = _json_bytes(dict(payload))
        path = "/v1/agent-host/channel-events"
        if len(self.shared_secret) < 32:
            return {"status": "failed", "error": "AGENT_HOST_AUTH_UNCONFIGURED"}
        timestamp = str(int(time.time()))
        canonical = "\n".join(
            (timestamp, "POST", path, hashlib.sha256(body).hexdigest())
        ).encode("utf-8")
        signature = hmac.new(
            self.shared_secret.encode("utf-8"), canonical, hashlib.sha256
        ).hexdigest()
        request = Request(
            self.base_url + path,
            data=body,
            method="POST",
            headers={
                "X-Agent-Principal": "openjarvis-channel",
                "X-Agent-Timestamp": timestamp,
                "X-Agent-Signature": signature,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                value = json.loads(response.read(256 * 1024).decode("utf-8"))
        except HTTPError as exc:
            logger.warning("Agent Host channel ingress rejected code=%s", exc.code)
            return {"status": "failed", "error": f"AGENT_HOST_HTTP_{exc.code}"}
        except (URLError, TimeoutError, OSError, UnicodeError, json.JSONDecodeError):
            logger.warning("Agent Host channel ingress unavailable")
            return {"status": "failed", "error": "AGENT_HOST_UNAVAILABLE"}
        return (
            value
            if isinstance(value, dict)
            else {"status": "failed", "error": "AGENT_HOST_INVALID_RESPONSE"}
        )


@dataclass
class WhatsAppAgentHostGateway:
    """Provider-bound service used only by the generic V1.1 tool package."""

    channel: Any

    def _result(
        self,
        status: str,
        *,
        reason: str,
        delivery_status: str = "unknown",
        physical_effect_started: bool = False,
        operation_id: str | None = None,
        error: dict[str, str] | None = None,
        message_id: str | None = None,
        idempotent_replay: bool = False,
        artifact_id: str | None = None,
        voice_note: bool = False,
        events: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "delivery_status": delivery_status,
            "physical_effect_started": physical_effect_started,
            "provider": "baileys",
            "message_id": message_id,
            "idempotent_replay": idempotent_replay,
        }
        # ``voice_note`` belongs to the media result contract.  Do not add it
        # to the text-message payload: that package deliberately validates
        # with ``additionalProperties: false``.
        if voice_note:
            data["voice_note"] = True
        if artifact_id:
            data["artifact_id"] = artifact_id
        value: dict[str, Any] = {
            "status": status,
            "reason": reason,
            "data": data,
            "external_effects_started": physical_effect_started,
        }
        if operation_id:
            value["operation_id"] = operation_id
        if error:
            value["error"] = error
        if events:
            value["events"] = events
        return value

    def send_message(
        self,
        arguments: Mapping[str, Any],
        execution_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        if os.environ.get("AGENT_HOST_WHATSAPP_EXTERNAL", "0").strip().lower() not in {
            "1",
            "true",
            "yes",
        }:
            return self._result(
                "blocked",
                reason="WhatsApp external gate is disabled",
                error={
                    "code": "WHATSAPP_EXTERNAL_DISABLED",
                    "message": "external effect is not authorized",
                },
            )
        conversation_id = str(arguments.get("conversation_id", "")).strip()
        text = str(arguments.get("text", "")).strip()
        idempotency_key = str(arguments.get("idempotency_key", "")).strip()
        if (
            not _CONVERSATION_RE.fullmatch(conversation_id)
            or not text
            or not idempotency_key
        ):
            return self._result(
                "failed",
                reason="WhatsApp input is invalid",
                error={"code": "WHATSAPP_INPUT_INVALID", "message": "invalid input"},
            )
        store = getattr(self.channel, "_store", None)
        if store is None:
            return self._result(
                "failed",
                reason="WhatsApp store unavailable",
                error={
                    "code": "WHATSAPP_STORE_UNAVAILABLE",
                    "message": "store unavailable",
                },
            )
        prior = store.get_agent_host_outbound(idempotency_key)
        if prior:
            return {
                **prior,
                "data": {**dict(prior.get("data", {})), "idempotent_replay": True},
            }
        mapping = store.resolve_agent_host_conversation(conversation_id)
        if mapping is None:
            result = self._result(
                "ineligible",
                reason="Conversation reference is unknown",
                error={
                    "code": "WHATSAPP_CONVERSATION_UNKNOWN",
                    "message": "unknown conversation",
                },
            )
            store.save_agent_host_outbound(
                idempotency_key, _opaque("wa-op", idempotency_key), result
            )
            return result
        target_jid = _jid(mapping.get("jid"))
        if (
            not target_jid
            or target_jid not in _allowed_jids()
            or target_jid.endswith("@g.us")
        ):
            result = self._result(
                "blocked",
                reason="WhatsApp destination is not authorized",
                error={
                    "code": "WHATSAPP_DESTINATION_NOT_AUTHORIZED",
                    "message": "destination not authorized",
                },
            )
            store.save_agent_host_outbound(
                idempotency_key, _opaque("wa-op", idempotency_key), result
            )
            return result
        snapshot = self.channel.status_snapshot()
        if str(snapshot.get("status")) != "connected":
            result = self._result(
                "failed",
                reason="Baileys is not connected",
                error={
                    "code": "WHATSAPP_NOT_CONNECTED",
                    "message": "provider not connected",
                },
            )
            store.save_agent_host_outbound(
                idempotency_key, _opaque("wa-op", idempotency_key), result
            )
            return result
        operation_id = _opaque("wa-op", idempotency_key)
        try:
            ack = self.channel.send_and_wait(
                target_jid,
                text,
                conversation_id=conversation_id,
                timeout=float(os.environ.get("OPENJARVIS_WHATSAPP_SEND_TIMEOUT", "20")),
            )
            message_id = str(ack.get("message_id") or ack.get("id") or "") or None
            result = self._result(
                "completed",
                reason="Baileys acknowledged the message",
                delivery_status="sent",
                physical_effect_started=True,
                operation_id=operation_id,
                message_id=message_id,
            )
        except Exception as exc:
            # A timeout after writing to the bridge is deliberately unknown;
            # the Host idempotency key is retained and never auto-retried.
            result = self._result(
                "unknown",
                reason="Baileys result is unknown",
                delivery_status="unknown",
                physical_effect_started=True,
                operation_id=operation_id,
                error={"code": "WHATSAPP_SEND_UNKNOWN", "message": type(exc).__name__},
            )
        store.save_agent_host_outbound(idempotency_key, operation_id, result)
        return result

    def send_media(
        self,
        arguments: Mapping[str, Any],
        execution_context: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Deliver one Agent Host artifact through the existing Baileys bridge."""

        if os.environ.get("AGENT_HOST_WHATSAPP_EXTERNAL", "0").strip().lower() not in {
            "1",
            "true",
            "yes",
        }:
            return self._result(
                "blocked",
                reason="WhatsApp external gate is disabled",
                error={
                    "code": "WHATSAPP_EXTERNAL_DISABLED",
                    "message": "external effect is not authorized",
                },
            )
        conversation_id = str(arguments.get("conversation_id", "")).strip()
        artifact_id = str(arguments.get("artifact_id", "")).strip()
        artifact_path = str(arguments.get("artifact_path", "")).strip()
        filename = str(arguments.get("filename", "arquivo")).strip() or "arquivo"
        mime_type = str(arguments.get("mime_type", "")).strip().lower()
        voice_note = bool(arguments.get("voice_note", False))
        size = int(arguments.get("size", 0) or 0)
        sha256 = str(arguments.get("sha256", "")).strip().lower()
        idempotency_key = str(arguments.get("idempotency_key", "")).strip()
        if (
            not _CONVERSATION_RE.fullmatch(conversation_id)
            or not re.fullmatch(r"art-[0-9a-f-]{36}", artifact_id)
            or not idempotency_key
        ):
            return self._result(
                "failed",
                reason="WhatsApp media input is invalid",
                error={
                    "code": "WHATSAPP_MEDIA_INPUT_INVALID",
                    "message": "invalid input",
                },
                artifact_id=artifact_id or None,
            )
        store = getattr(self.channel, "_store", None)
        if store is None:
            return self._result(
                "failed",
                reason="WhatsApp store unavailable",
                error={
                    "code": "WHATSAPP_STORE_UNAVAILABLE",
                    "message": "store unavailable",
                },
                artifact_id=artifact_id,
            )
        prior = store.get_agent_host_outbound(idempotency_key)
        if prior:
            return {
                **prior,
                "data": {**dict(prior.get("data", {})), "idempotent_replay": True},
            }
        mapping = store.resolve_agent_host_conversation(conversation_id)
        if mapping is None:
            result = self._result(
                "ineligible",
                reason="Conversation reference is unknown",
                error={
                    "code": "WHATSAPP_CONVERSATION_UNKNOWN",
                    "message": "unknown conversation",
                },
                artifact_id=artifact_id,
            )
            store.save_agent_host_outbound(
                idempotency_key, _opaque("wa-op", idempotency_key), result
            )
            return result
        target_jid = _jid(mapping.get("jid"))
        if (
            not target_jid
            or target_jid not in _allowed_jids()
            or target_jid.endswith("@g.us")
        ):
            result = self._result(
                "blocked",
                reason="WhatsApp destination is not authorized",
                error={
                    "code": "WHATSAPP_DESTINATION_NOT_AUTHORIZED",
                    "message": "destination not authorized",
                },
                artifact_id=artifact_id,
            )
            store.save_agent_host_outbound(
                idempotency_key, _opaque("wa-op", idempotency_key), result
            )
            return result
        artifact_root = (
            Path(
                os.environ.get(
                    "OPENJARVIS_ARTIFACT_ROOT", r"F:\agente\artifacts\registry"
                )
            )
            .expanduser()
            .resolve()
        )
        raw_candidate = Path(artifact_path).expanduser()
        if _path_has_symlink(raw_candidate):
            return self._result(
                "ineligible",
                reason="artifact path contains a symlink",
                error={"code": "ARTIFACT_PATH_INVALID", "message": "artifact rejected"},
                artifact_id=artifact_id,
            )
        candidate = raw_candidate.resolve()
        try:
            candidate.relative_to(artifact_root)
        except ValueError:
            return self._result(
                "ineligible",
                reason="artifact path is outside the controlled registry",
                error={
                    "code": "ARTIFACT_PATH_OUTSIDE_REGISTRY",
                    "message": "artifact rejected",
                },
                artifact_id=artifact_id,
            )
        if candidate.is_symlink() or not candidate.is_file():
            return self._result(
                "ineligible",
                reason="artifact file is unavailable",
                error={
                    "code": "ARTIFACT_FILE_UNAVAILABLE",
                    "message": "artifact rejected",
                },
                artifact_id=artifact_id,
            )
        allowed_mime = {
            "image/png",
            "image/jpeg",
            "image/webp",
            "application/pdf",
            "text/csv",
            "text/plain",
            "audio/ogg",
            "audio/mpeg",
            "audio/mp4",
            "audio/wav",
            "audio/x-wav",
            "audio/webm",
        }
        if voice_note and not mime_type.startswith("audio/"):
            return self._result(
                "ineligible",
                reason="voice_note requires an audio artifact",
                error={
                    "code": "VOICE_NOTE_REQUIRES_AUDIO",
                    "message": "audio artifact required",
                },
                artifact_id=artifact_id,
            )
        if (
            mime_type not in allowed_mime
            or candidate.stat().st_size != size
            or size > 12 * 1024 * 1024
        ):
            return self._result(
                "ineligible",
                reason="artifact type or size is not allowed",
                error={
                    "code": "ARTIFACT_VALIDATION_FAILED",
                    "message": "artifact rejected",
                },
                artifact_id=artifact_id,
            )
        import hashlib as _hashlib

        digest = _hashlib.sha256(candidate.read_bytes()).hexdigest()
        if digest != sha256:
            return self._result(
                "ineligible",
                reason="artifact checksum changed",
                error={
                    "code": "ARTIFACT_CHECKSUM_MISMATCH",
                    "message": "artifact rejected",
                },
                artifact_id=artifact_id,
            )
        snapshot = self.channel.status_snapshot()
        if str(snapshot.get("status")) != "connected":
            result = self._result(
                "failed",
                reason="Baileys is not connected",
                error={
                    "code": "WHATSAPP_NOT_CONNECTED",
                    "message": "provider not connected",
                },
                artifact_id=artifact_id,
            )
            store.save_agent_host_outbound(
                idempotency_key, _opaque("wa-op", idempotency_key), result
            )
            return result
        operation_id = _opaque("wa-op", idempotency_key)
        try:
            ack = self.channel.send_media_and_wait(
                target_jid,
                str(candidate),
                mime_type=mime_type,
                filename=filename,
                caption=str(arguments.get("caption", "")),
                voice_note=voice_note,
                conversation_id=conversation_id,
                timeout=float(os.environ.get("OPENJARVIS_WHATSAPP_SEND_TIMEOUT", "30")),
            )
            message_id = str(ack.get("message_id") or ack.get("id") or "") or None
            result = self._result(
                "completed",
                reason="Baileys acknowledged the media",
                delivery_status="sent",
                physical_effect_started=True,
                operation_id=operation_id,
                message_id=message_id,
                artifact_id=artifact_id,
                voice_note=voice_note,
                events=[
                    {
                        "kind": "whatsapp.media.sent",
                        "payload": {
                            "artifact_id": artifact_id,
                            "delivery_status": "sent",
                            "provider": "baileys",
                        },
                        "dedupe_key": f"whatsapp-media:{idempotency_key}",
                    }
                ],
            )
        except Exception as exc:
            result = self._result(
                "unknown",
                reason="Baileys media result is unknown",
                delivery_status="unknown",
                physical_effect_started=True,
                operation_id=operation_id,
                artifact_id=artifact_id,
                error={
                    "code": "WHATSAPP_MEDIA_SEND_UNKNOWN",
                    "message": type(exc).__name__,
                },
            )
        store.save_agent_host_outbound(idempotency_key, operation_id, result)
        return result

    def get_outbound_operation(
        self,
        *,
        operation_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Read a durable result; never sends or replays an outbound action."""

        operation = str(operation_id or "").strip()
        idem = str(idempotency_key or "").strip()
        if bool(operation) == bool(idem):
            return {
                "status": "failed",
                "reason": "exactly one operation selector is required",
                "error": {
                    "code": "OUTBOUND_SELECTOR_INVALID",
                    "message": (
                        "exactly one operation_id or idempotency_key is required"
                    ),
                },
            }
        store = getattr(self.channel, "_store", None)
        if store is None:
            return {
                "status": "failed",
                "reason": "WhatsApp outbound store unavailable",
                "error": {
                    "code": "WHATSAPP_STORE_UNAVAILABLE",
                    "message": "outbound store unavailable",
                },
            }
        result = (
            store.get_agent_host_outbound(idem)
            if idem
            else store.get_agent_host_outbound_by_operation(operation)
        )
        if result is None:
            return {
                "status": "not_found",
                "reason": "No durable outbound result is available.",
                "operation_id": operation or None,
            }
        return dict(result)


class WhatsAppAgentHostIngress:
    def __init__(self, channel: Any) -> None:
        self.channel = channel
        self.client = AgentHostChannelClient()

    def __call__(self, message: ChannelMessage) -> None:
        jid = _jid(message.conversation_id)
        if not jid or jid.endswith("@g.us") or classify_jid(jid).value == "group":
            return
        conversation_id = conversation_id_for_jid(jid)
        principal_id = principal_id_for_jid(jid)
        store = getattr(self.channel, "_store", None)
        if store is not None:
            store.bind_agent_host_conversation(conversation_id, jid, principal_id)
        message_id = str(message.message_id or "").strip()
        idempotency_key = "wa-in:" + (
            message_id
            or hashlib.sha256(
                f"{conversation_id}\0{message.content}".encode("utf-8")
            ).hexdigest()[:40]
        )
        response = self.client.submit(
            {
                "channel": "whatsapp_baileys",
                "principal_id": principal_id,
                "conversation_id": conversation_id,
                "message": str(message.content or "")[:20_000],
                "idempotency_key": idempotency_key,
                "correlation_id": "wa-msg:" + (message_id or idempotency_key[6:]),
                "attachments": [
                    {
                        "path": str(message.metadata.get("media_path", "")),
                        "filename": str(message.metadata.get("media_filename", "")),
                        "mime_type": str(message.metadata.get("media_mime_type", "")),
                        "size": int(message.metadata.get("media_size", 0) or 0),
                        "sha256": str(message.metadata.get("media_sha256", "")),
                        "source": "whatsapp.inbound",
                    }
                ]
                if message.metadata.get("media_path")
                else [],
            }
        )
        if response.get("status") not in {"accepted", "duplicate"}:
            logger.warning(
                "Agent Host did not accept WhatsApp event status=%s",
                response.get("status"),
            )


def configure_whatsapp_agent_host(app: Any, channel: Any) -> WhatsAppAgentHostGateway:
    """Attach exactly one ingress callback and one gateway to the app."""

    gateway = getattr(app.state, "whatsapp_agent_host_gateway", None)
    if isinstance(gateway, WhatsAppAgentHostGateway) and gateway.channel is channel:
        return gateway
    ingress = WhatsAppAgentHostIngress(channel)
    register = getattr(channel, "on_message", None)
    if callable(register):
        register(ingress)
    gateway = WhatsAppAgentHostGateway(channel)
    app.state.whatsapp_agent_host_gateway = gateway
    app.state.whatsapp_agent_host_ingress = ingress
    return gateway


def get_whatsapp_agent_host_gateway(app: Any) -> WhatsAppAgentHostGateway | None:
    value = getattr(app.state, "whatsapp_agent_host_gateway", None)
    return value if isinstance(value, WhatsAppAgentHostGateway) else None


__all__ = [
    "AgentHostChannelClient",
    "WhatsAppAgentHostGateway",
    "WhatsAppAgentHostIngress",
    "configure_whatsapp_agent_host",
    "conversation_id_for_jid",
    "get_whatsapp_agent_host_gateway",
    "principal_id_for_jid",
]
