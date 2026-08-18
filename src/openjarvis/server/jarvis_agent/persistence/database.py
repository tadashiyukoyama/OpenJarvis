"""SQLite connection and transaction lifecycle."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from openjarvis.server.jarvis_agent.persistence.edge_migrations import (
    EDGE_SCHEMA_SQL,
    EDGE_SCHEMA_VERSION,
)
from openjarvis.server.jarvis_agent.persistence.migrations import (
    SCHEMA_SQL,
    SCHEMA_VERSION,
)


class SQLiteDatabase:
    def __init__(self, path: str | Path, *, busy_timeout_ms: int = 5_000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._busy_timeout_ms = busy_timeout_ms
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(
            self.path,
            timeout=self._busy_timeout_ms / 1000,
            isolation_level=None,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        return connection

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        connection = self._connect()
        try:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(SCHEMA_SQL)
            connection.executescript(EDGE_SCHEMA_SQL)
            connection.execute(
                "INSERT OR REPLACE INTO jarvis_agent_meta(key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            connection.execute(
                "INSERT OR REPLACE INTO jarvis_agent_meta(key, value) VALUES (?, ?)",
                ("edge_schema_version", str(EDGE_SCHEMA_VERSION)),
            )
        finally:
            connection.close()

    def integrity_check(self) -> str:
        connection = self._connect()
        try:
            return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        finally:
            connection.close()
