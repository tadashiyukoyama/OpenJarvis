"""Authenticated, least-privilege actions for the Jarvis voice tools.

The browser/Gemini session never receives OAuth tokens or WhatsApp auth state.
Read operations are bounded; all external mutations are intentionally exposed
as separate endpoints so the UI can require an explicit approval first.
"""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import threading
import time
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from openjarvis.channels.whatsapp.bridge_commands import (
    BridgeCommandError,
    BridgeCommandTimeout,
)
from openjarvis.channels.whatsapp.identity import is_supported_jid

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v1/jarvis/sources", tags=["jarvis-sources"])
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,256}$")
_MESSAGE_ID_RE = re.compile(r"^[A-Za-z0-9@._<>:+-]{1,256}$")
_STATUS_JID = "status@broadcast"
_approval_lock = threading.RLock()
_approvals: dict[str, tuple[str, float]] = {}
_APPROVAL_TTL_SECONDS = 120


def _disable_sensitive_caching(response: Response) -> None:
    """Prevent browsers and gateways from reusing authentication state."""

    response.headers["Cache-Control"] = "no-store, private, max-age=0"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"


class GmailSearchInput(BaseModel):
    query: str = Field(default="", max_length=500)
    max_results: int = Field(default=10, ge=1, le=25)


class GmailMessageInput(BaseModel):
    message_id: str = Field(min_length=1, max_length=256)


class GmailSendInput(BaseModel):
    to: str = Field(min_length=3, max_length=320)
    subject: str = Field(default="", max_length=998)
    body: str = Field(min_length=1, max_length=20_000)
    cc: str = Field(default="", max_length=2_000)


class WhatsAppSendInput(BaseModel):
    jid: str = Field(default="", max_length=80)
    contact_name: str = Field(default="", max_length=240)
    text: str = Field(min_length=1, max_length=4_000)


class WhatsAppHistoryInput(BaseModel):
    jid: str = Field(min_length=5, max_length=160)
    limit: int = Field(default=50, ge=1, le=50)


class WhatsAppMarkReadInput(BaseModel):
    jid: str = Field(min_length=5, max_length=160)
    message_ids: list[str] = Field(default_factory=list, max_length=50)


class WhatsAppReactionInput(BaseModel):
    message_ref: str = Field(min_length=20, max_length=80)
    reaction: str = Field(min_length=1, max_length=16)


class WhatsAppActionInput(BaseModel):
    operation: str = Field(min_length=1, max_length=32)
    jid: str = Field(default="", max_length=160)
    text: str = Field(default="", max_length=4_000)
    message_id: str = Field(default="", max_length=256)
    message_ids: list[str] = Field(default_factory=list, max_length=50)
    participant: str = Field(default="", max_length=160)
    from_me: bool = False
    quoted_text: str = Field(default="", max_length=4_000)
    reaction: str = Field(default="", max_length=16)
    values: list[str] = Field(default_factory=list, max_length=20)
    selectable_count: int = Field(default=1, ge=1, le=20)
    media_type: str = Field(default="", max_length=16)
    url: str = Field(default="", max_length=2_000)
    caption: str = Field(default="", max_length=4_000)
    mimetype: str = Field(default="", max_length=120)
    file_name: str = Field(default="", max_length=240)
    enabled: bool = True
    subject: str = Field(default="", max_length=240)
    participants: list[str] = Field(default_factory=list, max_length=100)
    setting: str = Field(default="", max_length=40)
    value: str = Field(default="", max_length=40)
    status_jids: list[str] = Field(default_factory=list, max_length=100)


class SourceApprovalInput(BaseModel):
    action: str = Field(min_length=1, max_length=64)


class WhatsAppResetInput(BaseModel):
    confirm: bool


def _require_approval(token: str, action: str) -> None:
    now = time.monotonic()
    with _approval_lock:
        record = _approvals.pop(token.strip(), None) if token.strip() else None
    if record is None or record[0] != action or record[1] < now:
        raise HTTPException(
            status_code=403, detail="Ação externa não foi aprovada pela interface"
        )


@router.post("/approval")
def issue_source_approval(payload: SourceApprovalInput) -> dict[str, str]:
    """Mint a one-use, short-lived approval token after the UI confirmation."""
    token = secrets.token_urlsafe(32)
    with _approval_lock:
        _approvals[token] = (payload.action, time.monotonic() + _APPROVAL_TTL_SECONDS)
    return {"approval_token": token, "action": payload.action}


def _gmail(request: Request) -> Any:
    """Resolve the connector that is actually connected in Data Sources.

    ``gmail`` is the OAuth REST connector; ``gmail_imap`` is the synchronized
    app-password Data Source used by the default Gmail card. Prefer OAuth
    when connected, otherwise use IMAP for read/search operations.
    """
    injected = getattr(request.app.state, "jarvis_gmail_connector", None)
    if injected is not None and injected.is_connected():
        return injected

    from openjarvis.connectors.gmail import GmailConnector
    from openjarvis.connectors.gmail_imap import GmailIMAPConnector

    oauth = GmailConnector()
    if oauth.is_connected():
        request.app.state.jarvis_gmail_connector = oauth
        return oauth
    imap = GmailIMAPConnector()
    if imap.is_connected():
        request.app.state.jarvis_gmail_connector = imap
        return imap
    request.app.state.jarvis_gmail_connector = oauth
    return oauth


def _gmail_capabilities(connector: Any) -> list[str]:
    return [
        operation
        for operation, method in (
            ("search", "search_messages"),
            ("read", "read_message"),
            ("send", "send_message"),
            ("archive", "archive_message"),
            ("trash", "delete_message"),
        )
        if callable(getattr(connector, method, None))
    ]


def _require_gmail(request: Request) -> Any:
    connector = _gmail(request)
    if not connector.is_connected():
        raise HTTPException(
            status_code=409,
            detail=(
                "Nenhum Data Source Gmail conectado. Conecte Gmail (IMAP) "
                "ou Gmail OAuth em Data Sources."
            ),
        )
    return connector


def _require_gmail_mutation(request: Request, operation: str) -> Any:
    connector = _require_gmail(request)
    if operation not in _gmail_capabilities(connector):
        raise HTTPException(
            status_code=501,
            detail=(
                "O Data Source Gmail (IMAP) está conectado para busca e leitura, "
                "mas essa ação exige conectar o Gmail OAuth."
            ),
        )
    return connector


def _validate_id(value: str, label: str = "ID") -> str:
    value = value.strip()
    pattern = _MESSAGE_ID_RE if label == "message_id" else _ID_RE
    if not pattern.fullmatch(value):
        raise HTTPException(status_code=400, detail=f"{label} inválido")
    return value


def _whatsapp(request: Request) -> Any:
    channel = getattr(request.app.state, "jarvis_whatsapp_channel", None)
    if channel is None:
        try:
            from openjarvis.channels.whatsapp_baileys import WhatsAppBaileysChannel

            channel = WhatsAppBaileysChannel(
                bus=getattr(request.app.state, "bus", None)
            )
            request.app.state.jarvis_whatsapp_channel = channel
        except Exception as exc:  # pragma: no cover - optional runtime
            raise HTTPException(
                status_code=503, detail="WhatsApp QR indisponível"
            ) from exc
    return channel


@router.get("/gmail/status")
def gmail_status(request: Request) -> dict[str, Any]:
    connector = _gmail(request)
    connector_id = getattr(connector, "connector_id", "gmail")
    return {
        "source": "gmail",
        "connector_id": connector_id,
        "mode": "imap" if connector_id == "gmail_imap" else "oauth",
        "connected": bool(connector.is_connected()),
        "capabilities": _gmail_capabilities(connector),
    }


@router.post("/gmail/search")
def gmail_search(payload: GmailSearchInput, request: Request) -> dict[str, Any]:
    connector = _require_gmail(request)
    try:
        return {
            "source": "gmail",
            "messages": connector.search_messages(payload.query, payload.max_results),
        }
    except Exception as exc:
        logger.warning("Jarvis Gmail search failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502, detail="Não foi possível consultar o Gmail"
        ) from exc


@router.post("/gmail/read")
def gmail_read(payload: GmailMessageInput, request: Request) -> dict[str, Any]:
    message_id = _validate_id(payload.message_id, "message_id")
    connector = _require_gmail(request)
    try:
        return {"source": "gmail", "message": connector.read_message(message_id)}
    except Exception as exc:
        logger.warning("Jarvis Gmail read failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502, detail="Não foi possível ler o e-mail"
        ) from exc


@router.post("/gmail/send")
def gmail_send(
    payload: GmailSendInput,
    request: Request,
    approval_token: str = Header(default="", alias="X-Jarvis-Approval"),
) -> dict[str, Any]:
    _require_approval(approval_token, "gmail_send_email")
    if any(
        "\r" in value or "\n" in value
        for value in (payload.to, payload.subject, payload.cc)
    ):
        raise HTTPException(status_code=400, detail="Cabeçalho de e-mail inválido")
    connector = _require_gmail_mutation(request, "send")
    try:
        result = connector.send_message(
            to=payload.to, subject=payload.subject, body=payload.body, cc=payload.cc
        )
        return {"source": "gmail", "status": "sent", "message_id": result.get("id", "")}
    except Exception as exc:
        logger.warning("Jarvis Gmail send failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502, detail="Não foi possível enviar o e-mail"
        ) from exc


@router.post("/gmail/archive")
def gmail_archive(
    payload: GmailMessageInput,
    request: Request,
    approval_token: str = Header(default="", alias="X-Jarvis-Approval"),
) -> dict[str, str]:
    _require_approval(approval_token, "gmail_archive_email")
    message_id = _validate_id(payload.message_id, "message_id")
    connector = _require_gmail_mutation(request, "archive")
    try:
        connector.archive_message(message_id)
        return {"source": "gmail", "status": "archived", "message_id": message_id}
    except Exception as exc:
        logger.warning("Jarvis Gmail archive failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502, detail="Não foi possível arquivar o e-mail"
        ) from exc


@router.post("/gmail/trash")
def gmail_trash(
    payload: GmailMessageInput,
    request: Request,
    approval_token: str = Header(default="", alias="X-Jarvis-Approval"),
) -> dict[str, str]:
    _require_approval(approval_token, "gmail_trash_email")
    message_id = _validate_id(payload.message_id, "message_id")
    connector = _require_gmail_mutation(request, "trash")
    try:
        connector.delete_message(message_id)
        return {"source": "gmail", "status": "trashed", "message_id": message_id}
    except Exception as exc:
        logger.warning("Jarvis Gmail trash failed: %s", type(exc).__name__)
        raise HTTPException(
            status_code=502, detail="Não foi possível mover o e-mail para a lixeira"
        ) from exc


@router.get("/whatsapp/status")
def whatsapp_status(request: Request, response: Response) -> dict[str, Any]:
    _disable_sensitive_caching(response)
    channel = _whatsapp(request)
    snapshot = getattr(channel, "status_snapshot", None)
    if callable(snapshot):
        return {"source": "whatsapp_baileys", **snapshot()}
    status = (
        channel.status().value
        if hasattr(channel.status(), "value")
        else str(channel.status())
    )
    return {
        "source": "whatsapp_baileys",
        "status": status,
        "qr_available": bool(getattr(channel, "_last_qr", "")),
    }


@router.post("/whatsapp/start")
def whatsapp_start(request: Request) -> dict[str, Any]:
    channel = _whatsapp(request)
    channel.connect()
    snapshot = getattr(channel, "status_snapshot", None)
    if callable(snapshot):
        return {"source": "whatsapp_baileys", **snapshot()}
    status = (
        channel.status().value
        if hasattr(channel.status(), "value")
        else str(channel.status())
    )
    return {
        "source": "whatsapp_baileys",
        "status": status,
        "qr_available": bool(getattr(channel, "_last_qr", "")),
    }


@router.post("/whatsapp/reset")
def whatsapp_reset(
    payload: WhatsAppResetInput,
    request: Request,
) -> dict[str, Any]:
    if not payload.confirm:
        raise HTTPException(
            status_code=400,
            detail="Confirme explicitamente a limpeza da sessão local",
        )
    channel = _whatsapp(request)
    reset = getattr(channel, "reset_auth_state", None)
    if not callable(reset):
        raise HTTPException(status_code=501, detail="Reset Baileys indisponível")
    try:
        reset()
        channel.connect()
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    snapshot = getattr(channel, "status_snapshot", None)
    if callable(snapshot):
        return {"source": "whatsapp_baileys", **snapshot()}
    return {
        "source": "whatsapp_baileys",
        "status": "connecting",
        "qr_available": bool(getattr(channel, "_last_qr", "")),
    }


@router.get("/whatsapp/qr")
def whatsapp_qr(request: Request, response: Response) -> dict[str, Any]:
    _disable_sensitive_caching(response)
    channel = _whatsapp(request)
    snapshot = getattr(channel, "qr_snapshot", None)
    if callable(snapshot):
        return {"source": "whatsapp_baileys", **snapshot()}
    qr = str(getattr(channel, "_last_qr", ""))
    status_snapshot = getattr(channel, "status_snapshot", None)
    details = status_snapshot() if callable(status_snapshot) else {}
    return {
        "source": "whatsapp_baileys",
        **details,
        "qr": qr,
        "available": bool(qr),
        "qr_generation": int(details.get("qr_generation", 0)),
        "qr_issued_at": details.get("qr_issued_at"),
    }


@router.get("/whatsapp/contacts")
def whatsapp_contacts(
    request: Request,
    query: str = Query(default="", max_length=160),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """Search the bounded local contact index."""
    channel = _whatsapp(request)
    return {
        "source": "whatsapp_baileys",
        "contacts": channel.search_contacts(query, limit),
    }


@router.get("/whatsapp/chats")
def whatsapp_chats(
    request: Request,
    query: str = Query(default="", max_length=160),
    limit: int = Query(default=20, ge=1, le=100),
) -> dict[str, Any]:
    """List or search chats ordered by latest indexed activity."""
    channel = _whatsapp(request)
    return {
        "source": "whatsapp_baileys",
        "chats": channel.search_chats(query, limit),
    }


@router.get("/whatsapp/messages")
def whatsapp_messages(
    request: Request,
    jid: str = Query(..., min_length=5, max_length=160),
    query: str = Query(default="", max_length=160),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Read bounded local history or search within one conversation."""
    jid = jid.strip()
    if not is_supported_jid(jid):
        raise HTTPException(status_code=400, detail="JID WhatsApp invalido")
    channel = _whatsapp(request)
    return {
        "source": "whatsapp_baileys",
        "jid": jid,
        "messages": channel.list_messages(jid, query=query, limit=limit),
    }


@router.get("/whatsapp/summary")
def whatsapp_summary(
    request: Request,
    jid: str = Query(..., min_length=5, max_length=160),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict[str, Any]:
    """Return a read-only context pack for Jarvis to summarize."""
    jid = jid.strip()
    if not is_supported_jid(jid):
        raise HTTPException(status_code=400, detail="JID WhatsApp invalido")
    channel = _whatsapp(request)
    return {
        "source": "whatsapp_baileys",
        "summary": channel.conversation_summary(jid, limit=limit),
    }


@router.post("/whatsapp/history")
def whatsapp_history(payload: WhatsAppHistoryInput, request: Request) -> dict[str, Any]:
    """Request one bounded older-history page; events arrive asynchronously."""
    jid = payload.jid.strip()
    if not is_supported_jid(jid):
        raise HTTPException(status_code=400, detail="JID WhatsApp invalido")
    channel = _whatsapp(request)
    if not channel.request_history(jid, limit=payload.limit):
        raise HTTPException(status_code=409, detail="Historico adicional indisponivel")
    return {"source": "whatsapp_baileys", "status": "requested", "jid": jid}


@router.post("/whatsapp/read")
def whatsapp_mark_read(
    payload: WhatsAppMarkReadInput,
    request: Request,
    approval_token: str = Header(default="", alias="X-Jarvis-Approval"),
) -> dict[str, Any]:
    """Mark indexed WhatsApp messages as read after one-use approval."""
    jid = payload.jid.strip()
    if not is_supported_jid(jid):
        raise HTTPException(status_code=400, detail="JID WhatsApp invalido")
    if any(not _MESSAGE_ID_RE.fullmatch(item.strip()) for item in payload.message_ids):
        raise HTTPException(status_code=400, detail="ID de mensagem WhatsApp invalido")
    _require_approval(approval_token, "whatsapp_mark_read")
    channel = _whatsapp(request)
    if not channel.mark_read(jid, payload.message_ids):
        raise HTTPException(
            status_code=409, detail="Mensagens indisponiveis para leitura"
        )
    return {
        "source": "whatsapp_baileys",
        "status": "read_requested",
        "jid": jid,
        "message_count": len(payload.message_ids),
    }


def _validate_whatsapp_jid(value: str, *, allow_status: bool = False) -> str:
    jid = value.strip()
    if is_supported_jid(jid, allow_status=allow_status):
        return jid
    raise HTTPException(status_code=400, detail="JID WhatsApp invalido")


async def _execute_whatsapp_command(
    channel: Any, command: dict[str, Any]
) -> dict[str, Any]:
    """Wait for a real bridge acknowledgement when the channel supports it."""

    execute_and_wait = getattr(channel, "execute_action_and_wait", None)
    try:
        if callable(execute_and_wait):
            return await asyncio.to_thread(execute_and_wait, command, timeout=15.0)
        if not channel.execute_action(command):
            raise HTTPException(status_code=409, detail="WhatsApp nao esta conectado")
        return {"legacy_acknowledgement": True}
    except BridgeCommandTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except BridgeCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/whatsapp/reaction")
async def whatsapp_reaction(
    payload: WhatsAppReactionInput,
    request: Request,
    approval_token: str = Header(default="", alias="X-Jarvis-Approval"),
) -> dict[str, Any]:
    """React to an indexed message using its opaque, server-resolved key."""

    channel = _whatsapp(request)
    try:
        preview = channel.reaction_preview(payload.message_ref, payload.reaction)
    except ValueError as exc:
        # Validate before consuming the one-use approval token.
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    _require_approval(approval_token, "whatsapp_react_message")
    try:
        result = await asyncio.to_thread(
            channel.react_to_message,
            payload.message_ref,
            payload.reaction,
            timeout=15.0,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except BridgeCommandTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except BridgeCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "source": "whatsapp_baileys",
        "status": "completed",
        "operation": "reaction",
        "target": preview,
        "result": result,
    }


@router.post("/whatsapp/reaction/preview")
async def whatsapp_reaction_preview(
    payload: WhatsAppReactionInput,
    request: Request,
) -> dict[str, Any]:
    """Return bounded confirmation metadata without mutating WhatsApp."""

    channel = _whatsapp(request)
    try:
        target = channel.reaction_preview(payload.message_ref, payload.reaction)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {
        "source": "whatsapp_baileys",
        "operation": "reaction",
        "target": target,
    }


@router.post("/whatsapp/action")
async def whatsapp_action(
    payload: WhatsAppActionInput,
    request: Request,
    approval_token: str = Header(default="", alias="X-Jarvis-Approval"),
) -> dict[str, Any]:
    """Run one bounded WhatsApp capability through the namespace bridge.

    Read-only metadata operations do not require approval. Every operation
    that sends, changes chats, groups, profile or privacy requires a one-use
    approval token, so voice delegation cannot silently mutate WhatsApp.
    """
    operation = payload.operation.strip().lower()
    if operation == "reaction":
        raise HTTPException(
            status_code=400,
            detail="Use whatsapp_react_message com uma referencia opaca de mensagem",
        )
    readonly = {"group_metadata", "privacy_read"}
    if operation not in {
        "reply",
        "mark_read",
        "poll",
        "media",
        "archive",
        "pin",
        "mute",
        "group_metadata",
        "group_create",
        "group_subject",
        "privacy_read",
        "privacy_update",
        "profile_status",
        "broadcast",
    }:
        raise HTTPException(status_code=400, detail="Operacao WhatsApp desconhecida")
    channel = _whatsapp(request)
    if operation == "mark_read":
        jid = _validate_whatsapp_jid(payload.jid)
        if any(
            not _MESSAGE_ID_RE.fullmatch(item.strip()) for item in payload.message_ids
        ):
            raise HTTPException(
                status_code=400, detail="ID de mensagem WhatsApp invalido"
            )
        _require_approval(approval_token, "whatsapp_mark_read")
        if not channel.mark_read(jid, payload.message_ids):
            raise HTTPException(
                status_code=409, detail="Mensagens indisponiveis para leitura"
            )
        return {
            "source": "whatsapp_baileys",
            "status": "accepted",
            "operation": operation,
        }
    command: dict[str, Any] = {"type": ""}
    if operation == "reply":
        command = {
            "type": "send",
            "kind": "reply",
            "jid": _validate_whatsapp_jid(payload.jid),
            "text": payload.text,
            "messageId": _validate_id(payload.message_id, "message_id"),
            "participant": payload.participant,
            "fromMe": payload.from_me,
            "quotedText": payload.quoted_text,
        }
    elif operation == "poll":
        if len(payload.values) < 2 or not payload.text.strip():
            raise HTTPException(
                status_code=400, detail="Enquete requer pergunta e opcoes"
            )
        command = {
            "type": "send",
            "kind": "poll",
            "jid": _validate_whatsapp_jid(payload.jid),
            "text": payload.text,
            "values": payload.values,
            "selectableCount": payload.selectable_count,
        }
    elif operation == "media":
        if not payload.url.startswith("https://"):
            raise HTTPException(status_code=400, detail="Midia exige URL HTTPS")
        command = {
            "type": "send",
            "kind": "media",
            "jid": _validate_whatsapp_jid(payload.jid),
            "mediaType": payload.media_type,
            "url": payload.url,
            "caption": payload.caption,
            "mimetype": payload.mimetype,
            "fileName": payload.file_name,
        }
    elif operation in {"archive", "pin", "mute"}:
        command = {
            "type": "chat_modify",
            "operation": operation,
            "jid": _validate_whatsapp_jid(payload.jid),
            "enabled": payload.enabled,
        }
    elif operation == "group_metadata":
        jid = _validate_whatsapp_jid(payload.jid)
        if not jid.endswith("@g.us"):
            raise HTTPException(status_code=400, detail="A operacao exige um grupo")
        command = {"type": "group_metadata", "jid": jid}
    elif operation == "group_create":
        if not payload.subject.strip() or not payload.participants:
            raise HTTPException(
                status_code=400, detail="Grupo requer assunto e participantes"
            )
        command = {
            "type": "group_create",
            "subject": payload.subject,
            "participants": [
                _validate_whatsapp_jid(participant)
                for participant in payload.participants
            ],
        }
    elif operation == "group_subject":
        jid = _validate_whatsapp_jid(payload.jid)
        if not jid.endswith("@g.us") or not payload.subject.strip():
            raise HTTPException(
                status_code=400, detail="Grupo e novo assunto sao obrigatorios"
            )
        command = {"type": "group_subject", "jid": jid, "subject": payload.subject}
    elif operation == "privacy_read":
        command = {"type": "privacy", "operation": "read"}
    elif operation == "privacy_update":
        if not payload.setting.strip() or not payload.value.strip():
            raise HTTPException(
                status_code=400, detail="Privacidade requer configuracao e valor"
            )
        command = {
            "type": "privacy",
            "operation": "update",
            "setting": payload.setting,
            "value": payload.value,
        }
    elif operation == "profile_status":
        if not payload.text.strip():
            raise HTTPException(status_code=400, detail="Status nao pode ser vazio")
        command = {"type": "profile_status", "text": payload.text}
    elif operation == "broadcast":
        if not payload.text.strip():
            raise HTTPException(status_code=400, detail="Broadcast requer texto")
        command = {
            "type": "send",
            "kind": "text",
            "jid": _STATUS_JID,
            "text": payload.text,
            "statusJids": payload.status_jids,
        }
    if operation not in readonly:
        _require_approval(approval_token, f"whatsapp_{operation}")
    result = await _execute_whatsapp_command(channel, command)
    return {
        "source": "whatsapp_baileys",
        "status": "completed",
        "operation": operation,
        "result": result,
    }


@router.post("/whatsapp/send")
async def whatsapp_send(
    payload: WhatsAppSendInput,
    request: Request,
    approval_token: str = Header(default="", alias="X-Jarvis-Approval"),
) -> dict[str, Any]:
    destination = payload.jid.strip()
    contact_name = payload.contact_name.strip()
    if destination and contact_name:
        raise HTTPException(
            status_code=400,
            detail="Informe um JID ou um nome de contato, nunca os dois",
        )
    if not destination and not contact_name:
        raise HTTPException(
            status_code=400,
            detail="Informe um JID WhatsApp ou um nome de contato",
        )
    channel = _whatsapp(request)
    if not destination:
        matches = channel.search_contacts(contact_name, 10)
        if not matches:
            raise HTTPException(
                status_code=404,
                detail="Nenhum contato WhatsApp encontrado com esse nome",
            )
        if len(matches) > 1:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "Mais de um contato corresponde ao nome informado",
                    "matches": matches,
                },
            )
        destination = str(matches[0]["jid"])
    if not is_supported_jid(destination):
        raise HTTPException(
            status_code=400,
            detail="Informe um JID WhatsApp valido ou um nome de contato resolvido",
        )
    _require_approval(approval_token, "whatsapp_send_message")
    send_and_wait = getattr(channel, "send_and_wait", None)
    try:
        if callable(send_and_wait):
            result = await asyncio.to_thread(
                send_and_wait,
                destination,
                payload.text,
                timeout=15.0,
            )
        else:
            if not channel.send(destination, payload.text):
                raise HTTPException(
                    status_code=409, detail="WhatsApp nao esta conectado"
                )
            result = {"legacy_acknowledgement": True}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BridgeCommandTimeout as exc:
        raise HTTPException(status_code=504, detail=str(exc)) from exc
    except BridgeCommandError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        "source": "whatsapp_baileys",
        "status": "sent",
        "jid": destination,
        "result": result,
    }


@router.post("/whatsapp/call")
async def whatsapp_call(request: Request) -> dict[str, Any]:
    # Baileys currently gives us QR/text transport only. Refuse clearly until
    # a reviewed media/WebRTC adapter is configured; never imply a call worked.
    raise HTTPException(
        status_code=501,
        detail=(
            "Chamadas de voz WhatsApp exigem um adaptador de mídia/WebRTC; "
            "ainda não configurado."
        ),
    )


__all__ = ["router"]
