from __future__ import annotations

import json
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from openjarvis.server.evolution_api import EvolutionApiClient, EvolutionApiConfig
from openjarvis.server.evolution_router import router


class _Response:
    def __init__(self, status_code: int, payload):
        self.status_code = status_code
        self.content = json.dumps(payload).encode("utf-8")


class _Provider:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def request(self, method, url, **_kwargs):
        self.calls.append((method, url))
        if "/fetchInstances" in url:
            return _Response(200, [{"instanceName": "jarvis"}])
        if "/connectionState/" in url:
            return _Response(200, {"instance": {"state": "open"}})
        if "/instance/connect/" in url:
            return _Response(200, {"code": "pairing-code"})
        return _Response(404, {"error": "not found"})


def _app(client: EvolutionApiClient | None = None):
    app = FastAPI()
    app.include_router(router)
    if client is not None:
        app.state.evolution_api_client = client
    return app


def test_status_is_fail_closed_when_key_is_missing(monkeypatch):
    monkeypatch.delenv("OPENJARVIS_EVOLUTION_API_KEY", raising=False)
    client = EvolutionApiClient(
        EvolutionApiConfig("http://127.0.0.1:8787", "", "jarvis", "w" * 32)
    )
    response = TestClient(_app(client)).get(
        "/v1/integrations/whatsapp/evolution/status"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["configured"] is False
    assert body["state"] == "not_configured"
    assert "kkkk" not in response.text


def test_status_and_qr_use_loopback_provider_without_exposing_key():
    provider = _Provider()
    client = EvolutionApiClient(
        EvolutionApiConfig("http://127.0.0.1:8787", "k" * 48, "jarvis", "w" * 32),
        client=provider,
    )
    with TestClient(_app(client)) as http:
        status = http.get("/v1/integrations/whatsapp/evolution/status")
        qr = http.get("/v1/integrations/whatsapp/evolution/qr")
    assert status.status_code == 200
    assert status.json()["connected"] is True
    assert qr.status_code == 200
    assert qr.json()["available"] is True
    assert qr.json()["qr"] == "pairing-code"
    assert "kkkk" not in status.text
    assert all("apikey" not in url.lower() for _, url in provider.calls)


def test_qr_does_not_create_an_instance_when_not_provisioned():
    class NoInstance(_Provider):
        def request(self, method, url, **kwargs):
            if "/fetchInstances" in url:
                return _Response(200, [])
            raise AssertionError("no QR/connection call is allowed without an instance")

    client = EvolutionApiClient(
        EvolutionApiConfig("http://127.0.0.1:8787", "k" * 48, "jarvis", "w" * 32),
        client=NoInstance(),
    )
    response = TestClient(_app(client)).get("/v1/integrations/whatsapp/evolution/qr")
    assert response.status_code == 200
    assert response.json()["state"] == "not_provisioned"
    assert response.json()["available"] is False


def test_provision_is_disabled_by_default_and_does_not_call_provider():
    class NoCall(_Provider):
        def request(self, method, url, **kwargs):
            if method == "GET" and "/fetchInstances" in url:
                return _Response(200, [])
            raise AssertionError("provisioning is disabled")

    client = EvolutionApiClient(
        EvolutionApiConfig("http://127.0.0.1:8787", "k" * 48, "jarvis", "w" * 32),
        client=NoCall(),
    )
    response = TestClient(_app(client)).post(
        "/v1/integrations/whatsapp/evolution/provision"
    )
    assert response.status_code == 200
    assert response.json()["error_code"] == "EVOLUTION_PROVISIONING_DISABLED"


def test_explicit_provisioning_uses_fixed_instance_payload():
    class CreateOnly(_Provider):
        def request(self, method, url, **kwargs):
            if method == "GET" and "/fetchInstances" in url:
                return _Response(200, [])
            if method == "POST" and "/instance/create" in url:
                assert kwargs["json"] == {
                    "instanceName": "jarvis",
                    "qrcode": True,
                    "integration": "WHATSAPP-BAILEYS",
                }
                return _Response(201, {"instance": {"instanceName": "jarvis"}})
            raise AssertionError((method, url))

    client = EvolutionApiClient(
        EvolutionApiConfig(
            "http://127.0.0.1:8787",
            "k" * 48,
            "jarvis",
            "w" * 32,
            provisioning_enabled=True,
        ),
        client=CreateOnly(),
    )
    response = TestClient(_app(client)).post(
        "/v1/integrations/whatsapp/evolution/provision"
    )
    assert response.status_code == 200
    assert response.json()["provisioned"] is True
    assert response.json()["provisioning_enabled"] is True


def test_webhook_requires_secret_and_forwards_only_opaque_identity(monkeypatch):
    config = EvolutionApiConfig("http://127.0.0.1:8787", "k" * 48, "jarvis", "w" * 32)
    client = EvolutionApiClient(config=config, client=_Provider())
    payload = {
        "event": "messages.upsert",
        "data": {
            "key": {"remoteJid": "5511999999999@s.whatsapp.net", "id": "wam_1"},
            "message": {"conversation": "Olá"},
        },
    }
    app = _app(client)
    with patch(
        "openjarvis.server.whatsapp_agent_host.AgentHostChannelClient.submit",
        return_value={"status": "accepted", "run_id": "run-1"},
    ) as submit:
        with TestClient(app) as http:
            denied = http.post(
                "/v1/integrations/whatsapp/evolution/webhook", json=payload
            )
            accepted = http.post(
                "/v1/integrations/whatsapp/evolution/webhook",
                headers={"X-Evolution-Webhook-Secret": "w" * 32},
                json=payload,
            )
    assert denied.status_code == 403
    assert accepted.status_code == 202
    body = accepted.json()
    assert body["message_id"] == "wam_1"
    assert "5511999999999" not in accepted.text
    sent = submit.call_args.args[0]
    assert sent["channel"] == "whatsapp_evolution"
    assert sent["conversation_id"].startswith("wa:")
    assert sent["principal_id"] != "5511999999999@s.whatsapp.net"


def test_webhook_ignores_groups_and_from_me_messages():
    config = EvolutionApiConfig("http://127.0.0.1:8787", "k" * 48, "jarvis", "w" * 32)
    client = EvolutionApiClient(config=config, client=_Provider())
    app = _app(client)
    with TestClient(app) as http:
        group = http.post(
            "/v1/integrations/whatsapp/evolution/webhook",
            headers={"X-Evolution-Webhook-Secret": "w" * 32},
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {"remoteJid": "123@g.us", "id": "g1"},
                    "message": {"conversation": "group"},
                },
            },
        )
        own = http.post(
            "/v1/integrations/whatsapp/evolution/webhook",
            headers={"X-Evolution-Webhook-Secret": "w" * 32},
            json={
                "event": "messages.upsert",
                "data": {
                    "key": {
                        "remoteJid": "5511@s.whatsapp.net",
                        "id": "o1",
                        "fromMe": True,
                    },
                    "message": {"conversation": "own"},
                },
            },
        )
    assert group.json() == {"status": "ignored", "reason": "group_destination"}
    assert own.json() == {"status": "ignored", "reason": "unsupported_event"}
