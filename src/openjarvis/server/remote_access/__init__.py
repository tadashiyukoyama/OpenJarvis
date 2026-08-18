"""Authenticated loopback gateway used by the optional remote test tunnel."""

from openjarvis.server.remote_access.app import create_gateway_app
from openjarvis.server.remote_access.config import GatewayConfig

__all__ = ["GatewayConfig", "create_gateway_app"]
