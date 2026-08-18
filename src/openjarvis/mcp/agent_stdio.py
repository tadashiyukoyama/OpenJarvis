"""JSON-lines STDIO entry point for the Jarvis Agent MCP facade."""

from __future__ import annotations

import json
import logging
import sys

from openjarvis.mcp.agent_client import AgentCoreClient, AgentCoreClientConfig
from openjarvis.mcp.agent_server import JarvisAgentMCPServer
from openjarvis.mcp.protocol import PARSE_ERROR, MCPRequest, MCPResponse

logger = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    server = JarvisAgentMCPServer(AgentCoreClient(AgentCoreClientConfig.from_env()))
    try:
        for line in sys.stdin:
            if not line.strip():
                continue
            try:
                request = MCPRequest.from_json(line)
                if request.id is None:
                    if request.method == "notifications/initialized":
                        server.handle(request)
                    continue
                response = server.handle(request)
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                response = MCPResponse.error_response(
                    0, PARSE_ERROR, "Invalid JSON-RPC request"
                )
            sys.stdout.write(response.to_json() + "\n")
            sys.stdout.flush()
    finally:
        server.close()


if __name__ == "__main__":
    main()
