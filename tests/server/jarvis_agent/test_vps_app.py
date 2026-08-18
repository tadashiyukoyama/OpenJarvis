from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from openjarvis.server.vps_app import create_vps_app


def test_vps_factory_uses_edge_runtime_and_minimal_health(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setenv("OPENJARVIS_HOME", str(tmp_path / "state"))
    monkeypatch.setenv("OPENJARVIS_CORE_MODE", "vps")
    monkeypatch.delenv("OPENJARVIS_EDGE_TOKEN_CURRENT", raising=False)

    app = create_vps_app()
    with TestClient(app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/v1/models").json()["data"][0]["id"] == "codex"
        assert app.state.codex_runtime.poll_history_only is True
        assert app.state.codex_runtime.history_poll_interval_seconds == 10.0
