"""Minimal factory entry point for the containerized OpenJarvis Core."""

from __future__ import annotations

import os

from fastapi import FastAPI

from openjarvis.server.app import create_app


def create_vps_app() -> FastAPI:
    """Build the web/Agent Core process without a VPS inference engine."""

    os.environ.setdefault("OPENJARVIS_CORE_MODE", "vps")
    origin = os.environ.get("OPENJARVIS_PUBLIC_ORIGIN", "").strip().rstrip("/")
    origins = [origin] if origin else []
    return create_app(
        None,
        "",
        cors_origins=origins,
    )


__all__ = ["create_vps_app"]
