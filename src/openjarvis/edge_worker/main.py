"""CLI entry point for the Windows Edge Worker."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
from logging.handlers import RotatingFileHandler
from pathlib import Path

from openjarvis.edge_worker.config import EdgeWorkerConfig
from openjarvis.edge_worker.mcp_relay import MCPRelayConfig, MCPRelayServer
from openjarvis.edge_worker.worker import EdgeWorker


async def _run() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for name in ("SIGINT", "SIGTERM"):
        value = getattr(signal, name, None)
        if value is not None:
            try:
                loop.add_signal_handler(value, stop.set)
            except NotImplementedError:
                pass
    relay_config = MCPRelayConfig.from_env()
    relay = MCPRelayServer(relay_config) if relay_config is not None else None
    if relay is not None:
        await relay.start()
    try:
        await EdgeWorker(EdgeWorkerConfig.from_env()).run_forever(stop)
    finally:
        if relay is not None:
            await relay.close()


def _configure_logging(level: int) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    log_file = os.environ.get("OPENJARVIS_EDGE_LOG_FILE", "").strip()
    if log_file:
        path = Path(log_file).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        max_bytes = int(os.environ.get("OPENJARVIS_EDGE_LOG_MAX_BYTES", "10485760"))
        backups = int(os.environ.get("OPENJARVIS_EDGE_LOG_BACKUP_COUNT", "5"))
        if max_bytes <= 0 or backups <= 0:
            raise ValueError("Edge log rotation values must be positive")
        handlers.append(
            RotatingFileHandler(
                path,
                maxBytes=max_bytes,
                backupCount=backups,
                encoding="utf-8",
            )
        )
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        handlers=handlers,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="OpenJarvis Windows Edge Worker")
    parser.add_argument("--log-level", default="INFO")
    options = parser.parse_args()
    _configure_logging(getattr(logging, options.log_level.upper(), logging.INFO))
    asyncio.run(_run())


if __name__ == "__main__":
    main()
