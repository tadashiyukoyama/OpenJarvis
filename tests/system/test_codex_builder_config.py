"""Configuration tests for the shared Codex runtime selected by SystemBuilder."""

from __future__ import annotations

from openjarvis.system.builder import _codex_app_server_config_from_environment


def test_codex_builder_uses_openjarvis_shared_endpoint(monkeypatch) -> None:
    monkeypatch.setenv("OPENJARVIS_CODEX_APP_SERVER_URL", "ws://127.0.0.1:8130")
    monkeypatch.setenv("CODEX_APP_SERVER_WS_URL", "ws://127.0.0.1:8131")

    config = _codex_app_server_config_from_environment()

    assert config is not None
    assert config.websocket_url == "ws://127.0.0.1:8130"
    assert config.reject_unhandled_server_requests is False
    assert config.experimental_api is True


def test_codex_builder_accepts_desktop_endpoint_as_shared_default(monkeypatch) -> None:
    monkeypatch.delenv("OPENJARVIS_CODEX_APP_SERVER_URL", raising=False)
    monkeypatch.setenv("CODEX_APP_SERVER_WS_URL", "ws://127.0.0.1:8130")

    config = _codex_app_server_config_from_environment()

    assert config is not None
    assert config.websocket_url == "ws://127.0.0.1:8130"
    assert config.reject_unhandled_server_requests is False
    assert config.experimental_api is True


def test_codex_builder_preserves_owned_stdio_fallback(monkeypatch) -> None:
    monkeypatch.delenv("OPENJARVIS_CODEX_APP_SERVER_URL", raising=False)
    monkeypatch.delenv("CODEX_APP_SERVER_WS_URL", raising=False)

    config = _codex_app_server_config_from_environment()

    assert config.websocket_url is None
    assert config.experimental_api is True
