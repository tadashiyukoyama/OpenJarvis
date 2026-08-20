"""Secure Gemini Live token provisioning for the browser Jarvis console.

Long-lived Google API keys stay in the backend process.  The browser receives
only a short-lived, single-use token suitable for a direct Live API WebSocket.
The secondary credential is technical failover, never quota rotation.
"""

from __future__ import annotations

import asyncio
import os
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Awaitable, Callable, Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from openjarvis.server.jarvis_operational_log import JarvisOperationalLogStore

GEMINI_TOKEN_URL = "https://generativelanguage.googleapis.com/v1beta/auth_tokens"
GEMINI_LIVE_MODEL_DEFAULT = "gemini-3.1-flash-live-preview"
GEMINI_LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1beta.GenerativeService."
    "BidiGenerateContentConstrained"
)

PRIMARY_KEY_ENV = "GEMINI_LIVE_API_KEY_PRIMARY"
FALLBACK_KEY_ENV = "GEMINI_LIVE_API_KEY_FALLBACK"
MODEL_ENV = "GEMINI_LIVE_MODEL"
HOME_ENV = "OPENJARVIS_HOME"
RUNTIME_ROOT_ENV = "OPENJARVIS_RUNTIME_ROOT"
OPERATIONAL_LOG_TIMEOUT_SECONDS = 2.0

jarvis_live_router = APIRouter(prefix="/v1/jarvis/live", tags=["jarvis-live"])


@dataclass(frozen=True)
class _Credential:
    slot: str
    value: str


@dataclass(frozen=True)
class GeminiLiveToken:
    token: str
    slot: str
    model: str
    expires_at: str


class GeminiLiveProvisioningError(RuntimeError):
    """Sanitized provisioning error that never contains a credential or token."""

    def __init__(
        self,
        message: str,
        *,
        kind: str,
        status_code: int = 503,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.kind = kind
        self.status_code = status_code
        self.retry_after_seconds = retry_after_seconds


TokenRequester = Callable[[str, dict], Awaitable[dict]]


class JarvisOperationalEventInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=160)
    thread_id: str = Field(min_length=1, max_length=256)
    project_cwd: str = Field(default="", max_length=1_024)
    event_type: str = Field(min_length=1, max_length=32)
    text: str = Field(min_length=1, max_length=4_000)
    occurred_at: int = Field(ge=0)


class GeminiLiveClientDiagnosticInput(BaseModel):
    """Content-free browser metrics for diagnosing audible Live interruptions."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"]
    session_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9-]+$")
    sequence: int = Field(ge=1, le=1_000_000)
    occurred_at: int = Field(ge=0)
    voice_state: str = Field(min_length=1, max_length=32)
    socket_state: int = Field(ge=0, le=3)
    transport: Literal["worklet", "scheduled-buffer"]
    transport_reason: str = Field(min_length=1, max_length=48)
    audio_context_state: str = Field(min_length=1, max_length=32)
    audio_context_sample_rate: int = Field(ge=0, le=192_000)
    base_latency_ms: float = Field(ge=0, le=10_000)
    output_latency_ms: float = Field(ge=0, le=10_000)
    audio_chunks: int = Field(ge=0, le=10_000_000)
    audio_bytes: int = Field(ge=0, le=10_000_000_000)
    last_chunk_gap_ms: float = Field(ge=0, le=600_000)
    max_chunk_gap_ms: float = Field(ge=0, le=600_000)
    chunk_gaps_over_250_ms: int = Field(ge=0, le=10_000_000)
    message_queue_max_delay_ms: float = Field(ge=0, le=600_000)
    queued_ms: int = Field(ge=0, le=60_000)
    prebuffer_ms: int = Field(ge=0, le=10_000)
    underruns: int = Field(ge=0, le=10_000_000)
    dropped_samples: int = Field(ge=0, le=10_000_000_000)
    interruptions: int = Field(ge=0, le=1_000_000)
    go_away_events: int = Field(ge=0, le=1_000_000)
    websocket_buffered_amount: int = Field(ge=0, le=1_000_000_000)


async def _google_token_request(api_key: str, payload: dict) -> dict:
    async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
        try:
            response = await client.post(
                GEMINI_TOKEN_URL,
                headers={
                    "x-goog-api-key": api_key,
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.RequestError as exc:
            raise GeminiLiveProvisioningError(
                "Não foi possível alcançar o serviço de sessão do Gemini Live.",
                kind="transient",
            ) from exc

    if response.status_code == 429:
        retry_after = response.headers.get("retry-after", "")
        retry_seconds = int(retry_after) if retry_after.isdigit() else None
        raise GeminiLiveProvisioningError(
            "O limite do Gemini Live foi atingido. "
            "O comando foi preservado para retomada.",
            kind="quota",
            status_code=429,
            retry_after_seconds=retry_seconds,
        )
    if response.status_code in {401, 403}:
        raise GeminiLiveProvisioningError(
            "A credencial do Gemini Live foi recusada.",
            kind="auth",
            status_code=response.status_code,
        )
    if response.status_code >= 500:
        raise GeminiLiveProvisioningError(
            "O serviço de sessão do Gemini Live está temporariamente indisponível.",
            kind="transient",
        )
    if response.status_code >= 400:
        raise GeminiLiveProvisioningError(
            "A configuração do Gemini Live foi recusada "
            f"(HTTP {response.status_code}).",
            kind="configuration",
            status_code=response.status_code,
        )

    try:
        data = response.json()
    except ValueError as exc:
        raise GeminiLiveProvisioningError(
            "O serviço do Gemini Live devolveu uma resposta inválida.",
            kind="transient",
        ) from exc
    if not isinstance(data, dict) or not isinstance(data.get("name"), str):
        raise GeminiLiveProvisioningError(
            "O serviço do Gemini Live não devolveu um token utilizável.",
            kind="transient",
        )
    return data


class GeminiLiveTokenBroker:
    """Provision one-use tokens with conservative, policy-safe failover."""

    def __init__(
        self,
        *,
        requester: TokenRequester = _google_token_request,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._requester = requester
        self._clock = clock
        self._cooldown_until: dict[str, float] = {}

    @staticmethod
    def model() -> str:
        return os.environ.get(MODEL_ENV, GEMINI_LIVE_MODEL_DEFAULT).strip() or (
            GEMINI_LIVE_MODEL_DEFAULT
        )

    @staticmethod
    def credentials() -> list[_Credential]:
        credentials: list[_Credential] = []
        primary = os.environ.get(PRIMARY_KEY_ENV, "").strip()
        fallback = os.environ.get(FALLBACK_KEY_ENV, "").strip()
        if primary:
            credentials.append(_Credential("primary", primary))
        if fallback:
            credentials.append(_Credential("fallback", fallback))
        return credentials

    def status(self) -> dict:
        configured = {credential.slot for credential in self.credentials()}
        now = self._clock()
        return {
            "configured": "primary" in configured,
            "primary_configured": "primary" in configured,
            "fallback_configured": "fallback" in configured,
            "model": self.model(),
            "websocket_endpoint": GEMINI_LIVE_WS_URL,
            "primary_available": self._cooldown_until.get("primary", 0) <= now,
            "fallback_available": self._cooldown_until.get("fallback", 0) <= now,
            "failover_policy": "auth_or_transient_only",
            "quota_policy": "preserve_and_wait",
        }

    @staticmethod
    def _payload() -> tuple[dict, str]:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=30)
        payload = {
            "uses": 1,
            "expireTime": expires.isoformat().replace("+00:00", "Z"),
            "newSessionExpireTime": (now + timedelta(minutes=1))
            .isoformat()
            .replace("+00:00", "Z"),
        }
        return payload, payload["expireTime"]

    async def create_token(self) -> GeminiLiveToken:
        credentials = self.credentials()
        if not any(credential.slot == "primary" for credential in credentials):
            raise GeminiLiveProvisioningError(
                "Configure a chave principal do Gemini Live no ambiente privado local.",
                kind="not_configured",
                status_code=503,
            )

        payload, expires_at = self._payload()
        now = self._clock()
        candidates = [
            credential
            for credential in credentials
            if self._cooldown_until.get(credential.slot, 0) <= now
        ]
        if not candidates:
            raise GeminiLiveProvisioningError(
                "As credenciais do Gemini Live estão em recuperação temporária.",
                kind="transient",
            )

        last_error: GeminiLiveProvisioningError | None = None
        for credential in candidates:
            attempts = 2 if credential.slot == "primary" else 1
            for attempt in range(attempts):
                try:
                    data = await self._requester(credential.value, payload)
                    return GeminiLiveToken(
                        token=data["name"],
                        slot=credential.slot,
                        model=self.model(),
                        expires_at=expires_at,
                    )
                except GeminiLiveProvisioningError as exc:
                    last_error = exc
                    if exc.kind == "quota":
                        # Quotas are per project. Never rotate keys to evade them.
                        raise
                    if exc.kind not in {"auth", "transient"}:
                        raise
                    if exc.kind == "transient" and attempt + 1 < attempts:
                        await asyncio.sleep(0.25)
                        continue
                    cooldown = 600 if exc.kind == "auth" else 60
                    self._cooldown_until[credential.slot] = self._clock() + cooldown
                    break

        if last_error is not None:
            raise GeminiLiveProvisioningError(
                "Não foi possível emitir uma sessão Gemini Live com as "
                "credenciais disponíveis.",
                kind=last_error.kind,
                status_code=last_error.status_code,
            ) from last_error
        raise GeminiLiveProvisioningError(
            "Nenhuma credencial do Gemini Live está disponível.",
            kind="transient",
        )


def _broker(request: Request) -> GeminiLiveTokenBroker:
    broker = getattr(request.app.state, "gemini_live_token_broker", None)
    if broker is None:
        broker = GeminiLiveTokenBroker()
        request.app.state.gemini_live_token_broker = broker
    return broker


def _operational_database_path() -> Path | None:
    home = os.environ.get(HOME_ENV, "").strip()
    if home:
        return Path(home).expanduser().resolve() / "operational-events.sqlite3"
    runtime_root = os.environ.get(RUNTIME_ROOT_ENV, "").strip()
    if runtime_root:
        return (
            Path(runtime_root).expanduser().resolve()
            / "jarvis"
            / "operational-events.sqlite3"
        )
    return None


def _operational_log(request: Request) -> JarvisOperationalLogStore:
    store = getattr(request.app.state, "jarvis_operational_log", None)
    if store is not None:
        return store
    store = JarvisOperationalLogStore(_operational_database_path())
    request.app.state.jarvis_operational_log = store
    return store


def _client_diagnostics(request: Request) -> deque[dict]:
    records = getattr(request.app.state, "gemini_live_client_diagnostics", None)
    if records is None:
        records = deque(maxlen=512)
        request.app.state.gemini_live_client_diagnostics = records
    return records


@jarvis_live_router.get("/status")
async def gemini_live_status(request: Request) -> dict:
    """Return non-secret configuration and failover status."""

    return _broker(request).status()


@jarvis_live_router.post("/token")
async def create_gemini_live_token(request: Request) -> dict:
    """Create a browser-safe, single-use Gemini Live token."""

    try:
        token = await _broker(request).create_token()
    except GeminiLiveProvisioningError as exc:
        detail = {
            "message": str(exc),
            "kind": exc.kind,
            "command_preserved": exc.kind == "quota",
            "retry_after_seconds": exc.retry_after_seconds,
        }
        raise HTTPException(status_code=exc.status_code, detail=detail) from exc
    return {
        "token": token.token,
        "credential_slot": token.slot,
        "fallback_active": token.slot == "fallback",
        "model": token.model,
        "expires_at": token.expires_at,
        "websocket_endpoint": GEMINI_LIVE_WS_URL,
    }


@jarvis_live_router.post("/diagnostics", status_code=202)
async def append_gemini_live_client_diagnostic(
    payload: GeminiLiveClientDiagnosticInput,
    request: Request,
) -> dict:
    """Retain a bounded, content-free browser audio diagnostic in memory."""

    record = {
        **payload.model_dump(mode="json"),
        "received_at": int(time.time() * 1_000),
    }
    _client_diagnostics(request).append(record)
    return {
        "accepted": True,
        "session_id": payload.session_id,
        "sequence": payload.sequence,
    }


@jarvis_live_router.get("/diagnostics")
async def list_gemini_live_client_diagnostics(
    request: Request,
    session_id: str | None = None,
    limit: int = 50,
) -> dict:
    """Return recent sanitized audio metrics for controlled diagnosis."""

    if session_id is not None and (
        not 8 <= len(session_id) <= 64
        or not all(character.isalnum() or character == "-" for character in session_id)
    ):
        raise HTTPException(status_code=400, detail="Invalid session_id")
    bounded_limit = min(200, max(1, limit))
    records = list(_client_diagnostics(request))
    if session_id is not None:
        records = [record for record in records if record["session_id"] == session_id]
    selected = records[-bounded_limit:]
    return {
        "schema_version": "1.0",
        "records": selected,
        "has_more": len(records) > len(selected),
    }


@jarvis_live_router.get("/events")
async def list_jarvis_operational_events(
    request: Request,
    thread_id: str,
    limit: int = 50,
) -> dict:
    """Return recent sanitized Jarvis events for one selected Codex thread."""

    if not thread_id.strip() or len(thread_id) > 256:
        raise HTTPException(status_code=400, detail="Invalid thread_id")
    try:
        events = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: _operational_log(request).list(
                    thread_id, limit=min(100, max(1, limit))
                )
            ),
            timeout=OPERATIONAL_LOG_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail="Jarvis operational memory is temporarily busy",
        ) from exc
    return {"thread_id": thread_id, "events": [event.to_dict() for event in events]}


@jarvis_live_router.post("/events")
async def append_jarvis_operational_event(
    payload: JarvisOperationalEventInput,
    request: Request,
) -> dict:
    """Persist one idempotent event after server-side credential redaction."""

    try:
        event = await asyncio.wait_for(
            asyncio.to_thread(
                lambda: _operational_log(request).append(
                    event_id=payload.event_id,
                    thread_id=payload.thread_id,
                    project_cwd=payload.project_cwd,
                    event_type=payload.event_type,
                    text=payload.text,
                    occurred_at=payload.occurred_at,
                )
            ),
            timeout=OPERATIONAL_LOG_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(
            status_code=503,
            detail="Jarvis operational memory is temporarily busy",
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return event.to_dict()


__all__ = [
    "GeminiLiveClientDiagnosticInput",
    "GeminiLiveProvisioningError",
    "GeminiLiveTokenBroker",
    "JarvisOperationalEventInput",
    "append_gemini_live_client_diagnostic",
    "append_jarvis_operational_event",
    "create_gemini_live_token",
    "gemini_live_status",
    "jarvis_live_router",
    "list_gemini_live_client_diagnostics",
    "list_jarvis_operational_events",
]
