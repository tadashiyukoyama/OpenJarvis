"""Boundary between frontend navigation and backend API paths."""

from __future__ import annotations

from fastapi.responses import JSONResponse

_BACKEND_ROOT_SEGMENTS = frozenset(
    {
        "api",
        "edge",
        "health",
        "healthz",
        "v1",
        "webhook",
        "webhooks",
    }
)


def is_backend_path(path: str) -> bool:
    """Return whether an unmatched path belongs to the backend namespace."""
    normalized = path.strip("/")
    if not normalized:
        return False
    root_segment = normalized.partition("/")[0].lower()
    return root_segment in _BACKEND_ROOT_SEGMENTS


def backend_not_found_response() -> JSONResponse:
    """Return a stable JSON error instead of leaking the SPA for unknown APIs."""
    return JSONResponse(
        status_code=404,
        content={
            "error": {
                "code": "route_not_found",
                "message": "Backend route not found.",
            }
        },
    )


__all__ = ["backend_not_found_response", "is_backend_path"]
