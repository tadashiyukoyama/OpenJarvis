"""Application-scoped dependency assembly for the Jarvis agent core."""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI

from openjarvis.server.jarvis_agent.adapters.acelerachat import AceleraChatAdapter
from openjarvis.server.jarvis_agent.adapters.acelerachat.webhooks import (
    AceleraChatWebhookService,
)
from openjarvis.server.jarvis_agent.adapters.codex import CodexAdapter, EdgeCodexAdapter
from openjarvis.server.jarvis_agent.adapters.operational import OperationalAdapter
from openjarvis.server.jarvis_agent.edge.codex_runtime import CodexEdgeRuntimeProxy
from openjarvis.server.jarvis_agent.edge.service import EdgeService
from openjarvis.server.jarvis_agent.persistence.sqlite import JarvisAgentStore
from openjarvis.server.jarvis_agent.registry.catalog import JarvisToolCatalog
from openjarvis.server.jarvis_agent.registry.execution_gates import ToolExecutionGates
from openjarvis.server.jarvis_agent.services.context import ContextService
from openjarvis.server.jarvis_agent.services.events import EventService
from openjarvis.server.jarvis_agent.services.orchestrator import (
    JarvisAgentOrchestrator,
)
from openjarvis.server.jarvis_agent.services.references import ReferenceService


def state_root() -> Path:
    configured = os.environ.get("OPENJARVIS_HOME", "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    runtime = os.environ.get("OPENJARVIS_RUNTIME_ROOT", "").strip()
    if runtime:
        return Path(runtime).expanduser().resolve() / "state"
    return Path.home() / ".openjarvis"


def get_orchestrator(app: FastAPI) -> JarvisAgentOrchestrator:
    existing = getattr(app.state, "jarvis_agent_orchestrator", None)
    if isinstance(existing, JarvisAgentOrchestrator):
        return existing

    store = JarvisAgentStore(state_root() / "jarvis-agent.sqlite3")
    references = ReferenceService(store)
    context = ContextService(store)
    events = EventService(store)
    edge = EdgeService(store=store, events=events, context=context)
    core_mode = os.environ.get("OPENJARVIS_CORE_MODE", "local").strip().lower()
    codex_adapter = (
        EdgeCodexAdapter(edge)
        if core_mode == "vps"
        else CodexAdapter(
            lambda: getattr(app.state, "codex_runtime", None),
            lambda: getattr(app.state, "agent", None),
        )
    )

    adapters = {
        "jarvis": OperationalAdapter(
            lambda: getattr(app.state, "jarvis_operational_log", None)
        ),
        "acelerachat": AceleraChatAdapter(references),
        "codex": codex_adapter,
    }
    orchestrator = JarvisAgentOrchestrator(
        store=store,
        catalog=JarvisToolCatalog(),
        adapters=adapters,
        context=context,
        events=events,
        edge=edge,
        execution_gates=ToolExecutionGates.from_environment(core_mode),
    )
    acelerachat = adapters["acelerachat"]
    orchestrator.acelerachat_webhooks = AceleraChatWebhookService(
        config=acelerachat.config,
        client=acelerachat.client,
        store=store,
        events=orchestrator.events,
        context=orchestrator.context,
    )
    orchestrator.acelerachat_webhooks.schedule_all()
    app.state.jarvis_agent_orchestrator = orchestrator
    app.state.jarvis_agent_store = store
    return orchestrator


def configure_vps_codex_runtime(app: FastAPI) -> None:
    """Expose remote Codex reads through Edge when this process is the VPS Core."""

    core_mode = os.environ.get("OPENJARVIS_CORE_MODE", "local").strip().lower()
    if core_mode != "vps" or isinstance(
        getattr(app.state, "codex_runtime", None), CodexEdgeRuntimeProxy
    ):
        return
    app.state.codex_runtime = CodexEdgeRuntimeProxy(get_orchestrator(app).edge)


__all__ = ["configure_vps_codex_runtime", "get_orchestrator", "state_root"]
