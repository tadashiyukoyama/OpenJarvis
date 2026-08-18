"""Authenticated reverse proxy for exposing one local OpenJarvis instance."""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, quote, urlparse

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse, StreamingResponse
from starlette.background import BackgroundTask

from openjarvis.server.remote_access.auth import GatewayAuth, GatewayCredentials
from openjarvis.server.remote_access.config import GatewayConfig
from openjarvis.server.remote_access.pages import (
    continuation_success,
    login_page,
    login_success,
    safe_next,
)
from openjarvis.server.remote_access.request_body import (
    ACELERACHAT_WEBHOOK_BODY_LIMIT,
    read_bounded_body,
)

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}
_FORWARDED_CLIENT_HEADERS = {
    "cf-connecting-ip",
    "forwarded",
    "x-forwarded-for",
    "x-real-ip",
}
_DESKTOP_REFRESH_PATH = re.compile(
    r"^v1/codex/threads/[A-Za-z0-9][A-Za-z0-9._-]{0,127}/desktop-refresh$"
)
_SIGNED_ACELERACHAT_WEBHOOK_PATH = "v1/jarvis/agent/providers/acelerachat/webhooks"
_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def _build_access_logger(config: GatewayConfig) -> logging.Logger:
    config.access_log_file.parent.mkdir(parents=True, exist_ok=True)
    logger_name = f"openjarvis.remote_access.{hash(config.access_log_file)}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        handler = RotatingFileHandler(
            config.access_log_file,
            maxBytes=1_000_000,
            backupCount=2,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger.addHandler(handler)
    return logger


def _audit_login(request: Request, logger: logging.Logger, outcome: str) -> None:
    client_ip = request.headers.get("cf-connecting-ip")
    if not client_ip and request.client:
        client_ip = request.client.host
    user_agent = " ".join(
        request.headers.get("user-agent", "unknown").replace("\r", "").splitlines()
    )[:180]
    logger.info(
        "event=login outcome=%s client=%s user_agent=%s",
        outcome,
        client_ip or "unknown",
        user_agent,
    )


def _cookie_request_is_same_origin(request: Request) -> bool:
    if request.method in _SAFE_METHODS:
        return True
    fetch_site = request.headers.get("sec-fetch-site", "").strip().lower()
    if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
        return False
    origin = request.headers.get("origin", "").strip()
    if not origin:
        return True
    parsed = urlparse(origin)
    return parsed.netloc.lower() == request.headers.get("host", "").lower()


async def _body_stream(response: httpx.Response) -> AsyncIterator[bytes]:
    try:
        async for chunk in response.aiter_raw():
            yield chunk
    except httpx.RequestError:
        return


def create_gateway_app(
    config: GatewayConfig | None = None,
    *,
    upstream_client: httpx.AsyncClient | None = None,
) -> FastAPI:
    """Create one isolated gateway instance from validated local configuration."""

    config = config or GatewayConfig.from_environment()
    credentials = GatewayCredentials.from_file(config.credentials_file)
    auth = GatewayAuth(credentials, config)
    access_logger = _build_access_logger(config)
    owns_client = upstream_client is None
    client = upstream_client or httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=45.0, write=15.0, pool=5.0),
        limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        follow_redirects=False,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if owns_client:
            await client.aclose()

    app = FastAPI(
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/__openjarvis/health")
    async def health() -> JSONResponse:
        return JSONResponse(
            {"status": "ok"},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/__openjarvis/login")
    async def login_form(request: Request):  # noqa: ANN202
        return login_page(safe_next(request.query_params.get("next")))

    @app.post("/__openjarvis/login")
    async def login_submit(request: Request):  # noqa: ANN202
        form = parse_qs((await request.body()).decode("utf-8", errors="replace"))
        supplied_user = form.get("username", [""])[0]
        supplied_password = form.get("password", [""])[0]
        next_path = safe_next(form.get("next", ["/jarvis"])[0])
        if not auth.credentials_match(supplied_user, supplied_password):
            _audit_login(request, access_logger, "rejected")
            return login_page(next_path, invalid=True)

        _audit_login(request, access_logger, "accepted")
        response = login_success(next_path, auth.issue_continuation(request))
        auth.set_session_cookie(response)
        return response

    @app.get("/__openjarvis/continue")
    async def login_continue(request: Request):  # noqa: ANN202
        token = request.query_params.get("token", "")
        next_path = safe_next(request.query_params.get("next"))
        if not token or not auth.consume_continuation(request, token):
            _audit_login(request, access_logger, "continuation_rejected")
            return login_page(next_path, invalid=True)
        _audit_login(request, access_logger, "continued")
        response = continuation_success(next_path)
        auth.set_session_cookie(response)
        return response

    @app.api_route(
        "/{path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    )
    async def proxy(path: str, request: Request):  # noqa: ANN202
        authorization_kind = auth.authorization_kind(request)
        signed_provider_webhook = bool(
            request.method == "POST" and path == _SIGNED_ACELERACHAT_WEBHOOK_PATH
        )
        if authorization_kind is None and not signed_provider_webhook:
            accepts_html = "text/html" in request.headers.get("accept", "")
            if request.method in {"GET", "HEAD"} and accepts_html:
                next_path = f"/{path}"
                if request.url.query:
                    next_path = f"{next_path}?{request.url.query}"
                return RedirectResponse(
                    f"/__openjarvis/login?next={quote(safe_next(next_path), safe='')}",
                    status_code=303,
                    headers={"Cache-Control": "no-store"},
                )
            return JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
                headers={
                    "WWW-Authenticate": 'Basic realm="OpenJarvis remote test"',
                    "Cache-Control": "no-store",
                },
            )
        if authorization_kind == "cookie" and not _cookie_request_is_same_origin(
            request
        ):
            return JSONResponse(
                {"detail": "Cross-site request rejected"},
                status_code=403,
                headers={"Cache-Control": "no-store"},
            )

        target = f"{config.origin}/{path}"
        if request.url.query:
            target = f"{target}?{request.url.query}"
        desktop_refresh = bool(
            request.method == "POST" and _DESKTOP_REFRESH_PATH.fullmatch(path)
        )
        headers = {
            key: value
            for key, value in request.headers.items()
            if key.lower() not in _HOP_BY_HOP
            and key.lower() not in {"authorization", "cookie", "host", "content-length"}
            and not (desktop_refresh and key.lower() in _FORWARDED_CLIENT_HEADERS)
            and not (desktop_refresh and key.lower() == "x-openjarvis-local-action")
        }
        if desktop_refresh:
            headers["X-OpenJarvis-Local-Action"] = "codex-desktop-refresh"
        try:
            body = (
                await read_bounded_body(request, ACELERACHAT_WEBHOOK_BODY_LIMIT)
                if signed_provider_webhook
                else await request.body()
            )
        except ValueError:
            return JSONResponse(
                {
                    "detail": {
                        "code": "WEBHOOK_INVALID_PAYLOAD",
                        "message": "Webhook exceeded the safe size limit.",
                    }
                },
                status_code=413,
                headers={"Cache-Control": "no-store"},
            )
        upstream_request = client.build_request(
            request.method,
            target,
            headers=headers,
            content=body,
        )
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.TimeoutException:
            access_logger.warning(
                "upstream_timeout method=%s path=/%s", request.method, path
            )
            return JSONResponse(
                {"detail": "OpenJarvis local service timed out"},
                status_code=504,
                headers={"Cache-Control": "no-store"},
            )
        except httpx.RequestError:
            access_logger.warning(
                "upstream_unavailable method=%s path=/%s", request.method, path
            )
            return JSONResponse(
                {"detail": "OpenJarvis local service is unavailable"},
                status_code=502,
                headers={"Cache-Control": "no-store"},
            )

        response_headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.lower() not in _HOP_BY_HOP and key.lower() != "content-length"
        }
        response_headers["Cache-Control"] = "no-store"
        response_headers["Referrer-Policy"] = "no-referrer"
        response_headers["X-Content-Type-Options"] = "nosniff"
        response_headers["X-Frame-Options"] = "DENY"
        response_headers["Permissions-Policy"] = (
            "camera=(), geolocation=(), microphone=(self)"
        )
        if upstream.headers.get("content-type", "").startswith("text/html"):
            response_headers["Clear-Site-Data"] = '"cache"'
        response = StreamingResponse(
            _body_stream(upstream),
            status_code=upstream.status_code,
            headers=response_headers,
            background=BackgroundTask(upstream.aclose),
        )
        if authorization_kind == "basic":
            auth.set_session_cookie(response)
        return response

    return app


__all__ = ["create_gateway_app"]
