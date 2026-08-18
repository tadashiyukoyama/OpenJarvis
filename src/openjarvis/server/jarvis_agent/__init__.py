"""Server-side Jarvis agent orchestration boundary."""

from fastapi import APIRouter

from openjarvis.server.jarvis_agent.api.router import router as agent_router
from openjarvis.server.jarvis_agent.edge.router import router as edge_router

router = APIRouter()
router.include_router(agent_router)
router.include_router(edge_router)

__all__ = ["router"]
