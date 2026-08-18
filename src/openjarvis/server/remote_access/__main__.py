"""Run the authenticated OpenJarvis remote-access gateway on loopback."""

from __future__ import annotations

import argparse

import uvicorn

from openjarvis.server.remote_access.app import create_gateway_app


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8140)
    parser.add_argument("--log-level", default="warning")
    args = parser.parse_args()
    if args.host not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("the authenticated gateway must bind to loopback")
    if not 1 <= args.port <= 65_535:
        parser.error("port must be between 1 and 65535")
    uvicorn.run(
        create_gateway_app(),
        host=args.host,
        port=args.port,
        log_level=args.log_level,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1,::1",
    )


if __name__ == "__main__":
    main()
