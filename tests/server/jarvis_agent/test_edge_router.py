from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from openjarvis.server.jarvis_agent.edge.config import EdgeCoreConfig
from openjarvis.server.jarvis_agent.edge.frames import (
    make_edge_frame,
    parse_edge_frame,
)
from openjarvis.server.jarvis_agent.edge.router import router
from openjarvis.server.jarvis_agent.edge.service import EdgeService
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.registry.catalog import JarvisToolCatalog
from openjarvis.server.jarvis_agent.services.context import ContextService
from openjarvis.server.jarvis_agent.services.events import EventService
from openjarvis.server.jarvis_agent.services.orchestrator import (
    JarvisAgentOrchestrator,
)


def _app(tmp_path: Path) -> tuple[FastAPI, JarvisAgentOrchestrator]:
    store = JarvisAgentStore(tmp_path / "agent.sqlite3")
    context = ContextService(store)
    events = EventService(store)
    edge = EdgeService(
        store=store,
        context=context,
        events=events,
        config=EdgeCoreConfig(
            device_id="desktop-1",
            token_current="edge-secret",
            token_previous="",
            token_previous_expires_at=None,
            heartbeat_interval_seconds=15,
            heartbeat_timeout_seconds=45,
            offer_accept_timeout_seconds=2,
            result_timeout_seconds=2,
        ),
    )
    orchestrator = JarvisAgentOrchestrator(
        store=store,
        catalog=JarvisToolCatalog(definitions=()),
        adapters={},
        context=context,
        events=events,
        edge=edge,
    )
    app = FastAPI()
    app.state.jarvis_agent_orchestrator = orchestrator
    app.include_router(router)
    return app, orchestrator


def _client_frame(
    frame_type: str,
    sequence: int,
    payload: dict,
    *,
    job_id: str | None = None,
) -> str:
    return make_edge_frame(
        frame_type=frame_type,
        device_id="desktop-1",
        sequence=sequence,
        payload=payload,
        job_id=job_id,
        from_client=True,
    ).wire_json()


def test_edge_rejects_invalid_device_token(tmp_path: Path) -> None:
    app, orchestrator = _app(tmp_path)
    with TestClient(app) as client:
        try:
            with client.websocket_connect(
                "/edge",
                headers={
                    "X-OpenJarvis-Device-ID": "desktop-1",
                    "Authorization": "Bearer wrong",
                },
            ):
                raise AssertionError("invalid token was accepted")
        except WebSocketDisconnect as exc:
            assert exc.code == 4401
    asyncio.run(orchestrator.close_async())


def test_edge_job_round_trip_and_status(tmp_path: Path) -> None:
    app, orchestrator = _app(tmp_path)
    result: dict = {}
    failure: list[BaseException] = []
    with TestClient(app) as client:
        with client.websocket_connect(
            "/edge",
            headers={
                "X-OpenJarvis-Device-ID": "desktop-1",
                "Authorization": "Bearer edge-secret",
            },
        ) as websocket:
            websocket.send_text(
                _client_frame(
                    "edge.register",
                    1,
                    {
                        "worker_version": "test",
                        "platform": "windows",
                        "capabilities": ["codex.status"],
                    },
                )
            )
            registered = parse_edge_frame(websocket.receive_text(), from_client=False)
            assert registered.type == "edge.registered"
            status = client.get("/v1/jarvis/agent/edge/status").json()
            assert status["connected_devices"] == 1

            def execute() -> None:
                try:
                    result.update(
                        orchestrator.edge.execute_job(
                            tool_id="codex.status",
                            arguments={},
                            context={
                                "session_id": "session-1",
                                "partition_key": "project::thread",
                                "project_key": r"D:\dev\workspaces\openjarvis",
                                "codex_thread_id": "thread-1",
                                "request_id": "action-1",
                            },
                            payload_hash="a" * 64,
                            capability="codex.status",
                            job_id="job-1",
                        )
                    )
                except BaseException as exc:
                    failure.append(exc)

            thread = threading.Thread(target=execute)
            thread.start()
            offer = parse_edge_frame(websocket.receive_text(), from_client=False)
            assert offer.type == "job.offer"
            attempt_id = offer.payload["attempt_id"]
            websocket.send_text(
                _client_frame(
                    "job.accepted",
                    2,
                    {"attempt_id": attempt_id},
                    job_id="job-1",
                )
            )
            assert (
                orchestrator.store.edge_sequences("desktop-1")["outbound_sequence"]
                == offer.sequence
            )
            websocket.send_text(
                _client_frame(
                    "job.succeeded",
                    3,
                    {
                        "attempt_id": attempt_id,
                        "status": "completed",
                        "summary": "Codex online.",
                        "data": {"connected": True},
                        "references": {},
                    },
                    job_id="job-1",
                )
            )
            thread.join(timeout=2)
            assert (
                orchestrator.store.edge_sequences("desktop-1")["outbound_sequence"]
                == offer.sequence
            )
            websocket.send_text(
                _client_frame(
                    "edge.heartbeat",
                    4,
                    {"active_job_ids": []},
                )
            )
            heartbeat_ack = parse_edge_frame(
                websocket.receive_text(), from_client=False
            )
            assert heartbeat_ack.type == "edge.heartbeat_ack"
            assert heartbeat_ack.payload["acknowledged_sequence"] == 4

    asyncio.run(orchestrator.close_async())
    assert failure == []
    assert result["summary"] == "Codex online."


def test_edge_device_revocation_requires_visual_channel(tmp_path: Path) -> None:
    app, orchestrator = _app(tmp_path)
    orchestrator.store.upsert_edge_device(
        {
            "device_id": "desktop-1",
            "status": "OFFLINE",
            "capabilities": [],
            "metadata": {},
            "updated_at": 1.0,
        }
    )

    with TestClient(app) as client:
        path = "/v1/jarvis/agent/edge/devices/desktop-1/revoke"
        assert client.post(path).status_code == 403
        response = client.post(path, headers={"X-Jarvis-Decision-Channel": "visual"})

    asyncio.run(orchestrator.close_async())
    assert response.json() == {"device_id": "desktop-1", "state": "REVOKED"}
    assert orchestrator.store.get_edge_device("desktop-1")["revoked"] is True
