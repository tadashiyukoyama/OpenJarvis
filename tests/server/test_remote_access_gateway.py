from __future__ import annotations

import re
from base64 import b64encode
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from openjarvis.server.remote_access import GatewayConfig, create_gateway_app
from openjarvis.server.remote_access.auth import GatewayCredentials
from openjarvis.server.remote_access.pages import safe_next


def _config(tmp_path: Path) -> GatewayConfig:
    credentials = tmp_path / "gateway.env"
    credentials.write_text(
        "OJ_GATEWAY_USER=cesar\nOJ_GATEWAY_PASSWORD=test-password\n",
        encoding="utf-8",
    )
    return GatewayConfig(
        origin="http://127.0.0.1:8127",
        credentials_file=credentials,
        access_log_file=tmp_path / "gateway.log",
        secure_cookie=False,
    )


def _basic_auth() -> str:
    encoded = b64encode(b"cesar:test-password").decode("ascii")
    return f"Basic {encoded}"


def _upstream_client(captured: list[httpx.Request]) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(
            200,
            headers={"content-type": "text/html; charset=utf-8"},
            stream=httpx.ByteStream(b"<html>OpenJarvis</html>"),
        )

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_credentials_are_strict_and_never_optional(tmp_path: Path) -> None:
    path = tmp_path / "gateway.env"
    path.write_text(
        "OJ_GATEWAY_USER=cesar\nOJ_GATEWAY_PASSWORD='safe value'\n",
        encoding="utf-8",
    )
    credentials = GatewayCredentials.from_file(path)
    assert credentials.username == "cesar"
    assert credentials.password == "safe value"

    path.write_text("OJ_GATEWAY_USER=cesar\nUNKNOWN=value\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="Invalid gateway credential file"):
        GatewayCredentials.from_file(path)


def test_config_rejects_non_loopback_origin(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="loopback"):
        GatewayConfig(
            origin="https://example.com",
            credentials_file=tmp_path / "gateway.env",
            access_log_file=tmp_path / "gateway.log",
        )


@pytest.mark.parametrize(
    "untrusted",
    [
        "https://evil.example",
        "//evil.example",
        "/\\evil.example",
        "/%5cevil.example",
        "/%2f%2fevil.example",
        "/jarvis\nX-Injected: true",
    ],
)
def test_safe_next_rejects_external_or_ambiguous_targets(untrusted: str) -> None:
    assert safe_next(untrusted) == "/jarvis"


def test_safe_next_preserves_an_internal_route_and_query() -> None:
    assert safe_next("/jarvis?thread=thread-1") == "/jarvis?thread=thread-1"


def test_unauthenticated_browser_and_api_are_separated(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []
    app = create_gateway_app(
        _config(tmp_path), upstream_client=_upstream_client(captured)
    )
    with TestClient(app, follow_redirects=False) as client:
        browser = client.get("/jarvis", headers={"accept": "text/html"})
        api = client.get("/v1/jarvis/agent/catalog")
        health = client.get("/__openjarvis/health")

    assert browser.status_code == 303
    assert browser.headers["location"].startswith("/__openjarvis/login")
    assert api.status_code == 401
    assert api.headers["www-authenticate"].startswith("Basic")
    assert health.json() == {"status": "ok"}
    assert captured == []


def test_only_exact_acelerachat_webhook_post_bypasses_browser_auth(
    tmp_path: Path,
) -> None:
    captured: list[httpx.Request] = []
    app = create_gateway_app(
        _config(tmp_path), upstream_client=_upstream_client(captured)
    )
    webhook_path = "/v1/jarvis/agent/providers/acelerachat/webhooks"
    with TestClient(app) as client:
        accepted = client.post(
            webhook_path,
            headers={
                "X-AceleraChat-Delivery": "delivery",
                "X-AceleraChat-Signature": "sha256=test",
            },
            content=b"{}",
        )
        wrong_method = client.get(webhook_path)
        wrong_path = client.post(f"{webhook_path}/other", content=b"{}")

    assert accepted.status_code == 200
    assert wrong_method.status_code == 401
    assert wrong_path.status_code == 401
    assert len(captured) == 1
    assert captured[0].headers["x-acelerachat-delivery"] == "delivery"


def test_acelerachat_webhook_body_is_bounded_before_proxying(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []
    app = create_gateway_app(
        _config(tmp_path), upstream_client=_upstream_client(captured)
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/jarvis/agent/providers/acelerachat/webhooks",
            content=b"x" * (1024 * 1024 + 1),
        )

    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "WEBHOOK_INVALID_PAYLOAD"
    assert captured == []


def test_login_continuation_creates_browser_session(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []
    app = create_gateway_app(
        _config(tmp_path), upstream_client=_upstream_client(captured)
    )
    with TestClient(app, follow_redirects=False) as client:
        login = client.post(
            "/__openjarvis/login",
            content="username=cesar&password=test-password&next=%2Fjarvis",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        match = re.search(r"token=([^&\"]+)&amp;next=", login.text)
        assert match is not None
        continuation = client.get(
            f"/__openjarvis/continue?token={match.group(1)}&next=%2Fjarvis"
        )
        proxied = client.get("/jarvis", headers={"accept": "text/html"})

    assert login.status_code == 200
    assert continuation.status_code == 200
    assert "SESSÃO ATIVA" in continuation.text
    assert proxied.status_code == 200
    assert proxied.text == "<html>OpenJarvis</html>"
    assert len(captured) == 1


def test_basic_auth_is_not_forwarded_and_desktop_refresh_is_trusted(
    tmp_path: Path,
) -> None:
    captured: list[httpx.Request] = []
    app = create_gateway_app(
        _config(tmp_path), upstream_client=_upstream_client(captured)
    )
    with TestClient(app) as client:
        response = client.post(
            "/v1/codex/threads/thread-1/desktop-refresh",
            headers={
                "authorization": _basic_auth(),
                "cf-connecting-ip": "203.0.113.10",
                "x-openjarvis-local-action": "untrusted",
            },
            json={"reason": "manual"},
        )

    assert response.status_code == 200
    assert len(captured) == 1
    request = captured[0]
    assert request.headers.get("authorization") is None
    assert request.headers.get("cf-connecting-ip") is None
    assert request.headers["x-openjarvis-local-action"] == "codex-desktop-refresh"


def test_cookie_authenticated_cross_site_mutation_is_rejected(tmp_path: Path) -> None:
    captured: list[httpx.Request] = []
    app = create_gateway_app(
        _config(tmp_path), upstream_client=_upstream_client(captured)
    )
    with TestClient(app) as client:
        client.post(
            "/__openjarvis/login",
            content="username=cesar&password=test-password&next=%2Fjarvis",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        response = client.post(
            "/v1/jarvis/agent/actions/action-1/decision",
            headers={"origin": "https://evil.example"},
            json={"decision": "approve"},
        )

    assert response.status_code == 403
    assert captured == []


def test_cookie_mutation_rejects_cross_site_fetch_without_origin(
    tmp_path: Path,
) -> None:
    captured: list[httpx.Request] = []
    app = create_gateway_app(
        _config(tmp_path), upstream_client=_upstream_client(captured)
    )
    with TestClient(app) as client:
        client.post(
            "/__openjarvis/login",
            content="username=cesar&password=test-password&next=%2Fjarvis",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        response = client.post(
            "/v1/jarvis/agent/actions/action-1/decision",
            headers={"sec-fetch-site": "cross-site"},
            json={"decision": "approve"},
        )

    assert response.status_code == 403
    assert captured == []
