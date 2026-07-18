"""Provider-neutral persistent identity for external conversations.

This module defines the durable boundary between an OpenJarvis conversation
and a provider-owned conversation.  It deliberately knows nothing about any
specific provider or client lifecycle. Store timestamps are Unix epoch
seconds (UTC), and the store uses one short-lived SQLite connection per
operation.
"""

from __future__ import annotations

import hashlib
import hmac
import math
import sqlite3
import time
from abc import ABC, abstractmethod
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Iterator


BINDING_DIGEST_SCHEMA_VERSION = "v1"
SCHEMA_VERSION = 1
DEFAULT_BUSY_TIMEOUT_MS = 5_000
MAX_CONVERSATION_ID_LENGTH = 256
MAX_SCOPE_ID_LENGTH = 256
MAX_AGENT_NAME_LENGTH = 128
MAX_EXTERNAL_RUNTIME_LENGTH = 128
MAX_EXTERNAL_CONVERSATION_ID_LENGTH = 512
MAX_OWNER_TOKEN_LENGTH = 256


class ConversationBindingError(RuntimeError):
    """Base error for conversation-binding store failures."""


class ConversationBindingAlreadyBoundError(ConversationBindingError):
    """The requested key already has a durable binding."""


class ConversationBindingNotFoundError(ConversationBindingError):
    """The requested reservation does not exist."""


class ConversationBindingOwnerError(PermissionError, ConversationBindingError):
    """The caller does not own the active reservation."""


class ConversationBindingReservationExpiredError(ConversationBindingOwnerError):
    """The caller's reservation lease is no longer valid."""


class ConversationBindingState(str, Enum):
    """Durable binding states plus the non-persisted BUSY result state."""

    RESERVED = "RESERVED"
    BOUND = "BOUND"
    BUSY = "BUSY"


def _required_text(value: object, field_name: str, max_length: int) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"{field_name} exceeds the maximum length")
    if "\x00" in value:
        raise ValueError(f"{field_name} must not contain NUL")
    return value


def _timestamp(value: object, field_name: str) -> float:
    if value is None:
        return time.time()
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a finite number")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"{field_name} must be a finite number")
    return result


@dataclass(frozen=True, slots=True, repr=False)
class ConversationIdentity:
    """Stable internal identity for one OpenJarvis conversation."""

    conversation_id: str
    scope_id: str

    def __post_init__(self) -> None:
        _required_text(
            self.conversation_id,
            "conversation_id",
            MAX_CONVERSATION_ID_LENGTH,
        )
        _required_text(self.scope_id, "scope_id", MAX_SCOPE_ID_LENGTH)

    def __repr__(self) -> str:
        return (
            "ConversationIdentity(conversation_id=<redacted>, "
            "scope_id=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ConversationBindingKey:
    """Provider-neutral lookup key for one external conversation binding."""

    identity: ConversationIdentity
    agent_name: str
    external_runtime: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, ConversationIdentity):
            raise TypeError("identity must be a ConversationIdentity")
        _required_text(self.agent_name, "agent_name", MAX_AGENT_NAME_LENGTH)
        _required_text(
            self.external_runtime,
            "external_runtime",
            MAX_EXTERNAL_RUNTIME_LENGTH,
        )

    @property
    def digest(self) -> str:
        """Return the deterministic, non-reversible lookup digest."""

        canonical = "\x00".join(
            (
                BINDING_DIGEST_SCHEMA_VERSION,
                self.identity.conversation_id,
                self.identity.scope_id,
                self.agent_name,
                self.external_runtime,
            )
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()

    @property
    def key_digest(self) -> str:
        """Alias that makes the stored field name explicit."""

        return self.digest

    def __repr__(self) -> str:
        return (
            "ConversationBindingKey(identity=<redacted>, "
            "agent_name=<redacted>, external_runtime=<redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ExternalConversationBinding:
    """Sanitized durable binding record returned by the store."""

    binding_key_digest: str
    agent_name: str
    external_runtime: str
    external_conversation_id: str | None
    state: ConversationBindingState
    created_at: float
    updated_at: float
    version: int = SCHEMA_VERSION

    @property
    def key_digest(self) -> str:
        return self.binding_key_digest

    def __repr__(self) -> str:
        return (
            "ExternalConversationBinding("
            f"binding_key_digest={self.binding_key_digest!r}, "
            "agent_name=<redacted>, external_runtime=<redacted>, "
            "external_conversation_id=<redacted>, "
            f"state={self.state.value!r}, version={self.version})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ConversationBindingReservation:
    """Result of attempting to reserve a binding key."""

    binding: ExternalConversationBinding
    state: ConversationBindingState
    acquired: bool
    lease_expires_at: float | None = None
    owner_token: str | None = None

    @property
    def busy(self) -> bool:
        return self.state is ConversationBindingState.BUSY

    @property
    def key_digest(self) -> str:
        return self.binding.binding_key_digest

    def __repr__(self) -> str:
        return (
            "ConversationBindingReservation("
            f"key_digest={self.key_digest!r}, state={self.state.value!r}, "
            f"acquired={self.acquired}, busy={self.busy}, "
            f"lease_expires_at={self.lease_expires_at!r}, "
            "owner_token=<redacted>)"
        )


class ConversationBindingStore(ABC):
    """Abstract provider-neutral conversation-binding store."""

    @abstractmethod
    def lookup(self, key: ConversationBindingKey) -> ExternalConversationBinding | None:
        """Return the current binding for ``key`` if present."""

    @abstractmethod
    def reserve(
        self,
        key: ConversationBindingKey,
        owner_token: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> ConversationBindingReservation:
        """Atomically reserve an unbound key or report its current state."""

    @abstractmethod
    def complete_reservation(
        self,
        key: ConversationBindingKey,
        owner_token: str,
        external_conversation_id: str,
        now: float | None = None,
    ) -> ExternalConversationBinding:
        """Atomically convert the caller's reservation into a binding."""

    @abstractmethod
    def release_reservation(
        self,
        key: ConversationBindingKey,
        owner_token: str,
        now: float | None = None,
    ) -> bool:
        """Release a caller-owned reservation; never remove a BOUND row."""


class SQLiteConversationBindingStore(ConversationBindingStore):
    """SQLite implementation with one short-lived connection per operation."""

    def __init__(
        self,
        database_path: str | Path,
        *,
        busy_timeout_ms: int = DEFAULT_BUSY_TIMEOUT_MS,
    ) -> None:
        if isinstance(database_path, Path):
            path = database_path
        elif isinstance(database_path, str) and database_path:
            path = Path(database_path)
        else:
            raise ValueError("database_path must be explicitly provided")
        if (
            isinstance(busy_timeout_ms, bool)
            or not isinstance(busy_timeout_ms, int)
            or busy_timeout_ms <= 0
        ):
            raise ValueError("busy_timeout_ms must be a positive integer")

        path.parent.mkdir(parents=True, exist_ok=True)
        self._database_path = path
        self._busy_timeout_ms = busy_timeout_ms
        self._initialize_schema()

    def __repr__(self) -> str:
        return "<SQLiteConversationBindingStore>"

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(
            str(self._database_path),
            timeout=self._busy_timeout_ms / 1000,
        )
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self._busy_timeout_ms}")
        connection.execute("PRAGMA foreign_keys = ON")
        try:
            yield connection
        finally:
            connection.close()

    def _initialize_schema(self) -> None:
        with self._connection() as connection:
            current_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            if current_version not in (0, SCHEMA_VERSION):
                raise ConversationBindingError(
                    f"unsupported conversation binding schema: {current_version}"
                )
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS conversation_bindings (
                    binding_key_digest      TEXT PRIMARY KEY,
                    agent_name              TEXT NOT NULL,
                    external_runtime       TEXT NOT NULL,
                    external_conversation_id TEXT,
                    state                   TEXT NOT NULL,
                    created_at              REAL NOT NULL,
                    updated_at              REAL NOT NULL,
                    version                 INTEGER NOT NULL,
                    owner_token             TEXT,
                    lease_expires_at       REAL,
                    CHECK (state IN ('RESERVED', 'BOUND')),
                    CHECK (
                        (state = 'RESERVED'
                         AND external_conversation_id IS NULL
                         AND owner_token IS NOT NULL
                         AND lease_expires_at IS NOT NULL)
                        OR
                        (state = 'BOUND'
                         AND external_conversation_id IS NOT NULL
                         AND owner_token IS NULL
                         AND lease_expires_at IS NULL)
                    )
                );
                """
            )
            if current_version == 0:
                connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
            connection.commit()

    @staticmethod
    def _validate_key(key: ConversationBindingKey) -> ConversationBindingKey:
        if not isinstance(key, ConversationBindingKey):
            raise TypeError("key must be a ConversationBindingKey")
        return key

    @staticmethod
    def _validate_owner(owner_token: object) -> str:
        return _required_text(owner_token, "owner_token", MAX_OWNER_TOKEN_LENGTH)

    @staticmethod
    def _validate_lease(lease_seconds: object) -> float:
        if isinstance(lease_seconds, bool) or not isinstance(
            lease_seconds, (int, float)
        ):
            raise ValueError("lease_seconds must be a positive finite number")
        lease = float(lease_seconds)
        if not math.isfinite(lease) or lease <= 0:
            raise ValueError("lease_seconds must be a positive finite number")
        return lease

    @staticmethod
    def _validate_external_id(value: object) -> str:
        return _required_text(
            value,
            "external_conversation_id",
            MAX_EXTERNAL_CONVERSATION_ID_LENGTH,
        )

    @staticmethod
    def _row_to_binding(row: sqlite3.Row) -> ExternalConversationBinding:
        return ExternalConversationBinding(
            binding_key_digest=row["binding_key_digest"],
            agent_name=row["agent_name"],
            external_runtime=row["external_runtime"],
            external_conversation_id=row["external_conversation_id"],
            state=ConversationBindingState(row["state"]),
            created_at=float(row["created_at"]),
            updated_at=float(row["updated_at"]),
            version=int(row["version"]),
        )

    @staticmethod
    def _reservation(
        row: sqlite3.Row,
        *,
        state: ConversationBindingState,
        acquired: bool,
        owner_token: str | None = None,
    ) -> ConversationBindingReservation:
        binding = SQLiteConversationBindingStore._row_to_binding(row)
        return ConversationBindingReservation(
            binding=binding,
            state=state,
            acquired=acquired,
            lease_expires_at=(
                float(row["lease_expires_at"])
                if row["lease_expires_at"] is not None
                else None
            ),
            owner_token=owner_token,
        )

    def lookup(self, key: ConversationBindingKey) -> ExternalConversationBinding | None:
        key = self._validate_key(key)
        with self._connection() as connection:
            row = connection.execute(
                "SELECT binding_key_digest, agent_name, external_runtime, "
                "external_conversation_id, state, created_at, updated_at, "
                "version, owner_token, lease_expires_at "
                "FROM conversation_bindings WHERE binding_key_digest = ?",
                (key.digest,),
            ).fetchone()
        return self._row_to_binding(row) if row is not None else None

    def reserve(
        self,
        key: ConversationBindingKey,
        owner_token: str,
        lease_seconds: float,
        now: float | None = None,
    ) -> ConversationBindingReservation:
        key = self._validate_key(key)
        owner_token = self._validate_owner(owner_token)
        lease = self._validate_lease(lease_seconds)
        current_time = _timestamp(now, "now")
        expires_at = current_time + lease

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT binding_key_digest, agent_name, external_runtime, "
                    "external_conversation_id, state, created_at, updated_at, "
                    "version, owner_token, lease_expires_at "
                    "FROM conversation_bindings WHERE binding_key_digest = ?",
                    (key.digest,),
                ).fetchone()

                if row is None:
                    connection.execute(
                        "INSERT INTO conversation_bindings ("
                        "binding_key_digest, agent_name, external_runtime, state, "
                        "created_at, updated_at, version, owner_token, "
                        "lease_expires_at) VALUES (?, ?, ?, 'RESERVED', ?, ?, ?, ?, ?)",
                        (
                            key.digest,
                            key.agent_name,
                            key.external_runtime,
                            current_time,
                            current_time,
                            SCHEMA_VERSION,
                            owner_token,
                            expires_at,
                        ),
                    )
                    row = connection.execute(
                        "SELECT binding_key_digest, agent_name, external_runtime, "
                        "external_conversation_id, state, created_at, updated_at, "
                        "version, owner_token, lease_expires_at "
                        "FROM conversation_bindings WHERE binding_key_digest = ?",
                        (key.digest,),
                    ).fetchone()
                    connection.commit()
                    return self._reservation(
                        row,
                        state=ConversationBindingState.RESERVED,
                        acquired=True,
                        owner_token=owner_token,
                    )

                state = ConversationBindingState(row["state"])
                if state is ConversationBindingState.BOUND:
                    connection.commit()
                    return self._reservation(
                        row,
                        state=ConversationBindingState.BOUND,
                        acquired=False,
                    )

                existing_expiry = float(row["lease_expires_at"])
                existing_owner = row["owner_token"]
                lease_valid = existing_expiry > current_time
                if lease_valid and not hmac.compare_digest(
                    str(existing_owner), owner_token
                ):
                    connection.commit()
                    return self._reservation(
                        row,
                        state=ConversationBindingState.BUSY,
                        acquired=False,
                    )

                connection.execute(
                    "UPDATE conversation_bindings SET owner_token = ?, "
                    "lease_expires_at = ?, updated_at = ? "
                    "WHERE binding_key_digest = ?",
                    (owner_token, expires_at, current_time, key.digest),
                )
                row = connection.execute(
                    "SELECT binding_key_digest, agent_name, external_runtime, "
                    "external_conversation_id, state, created_at, updated_at, "
                    "version, owner_token, lease_expires_at "
                    "FROM conversation_bindings WHERE binding_key_digest = ?",
                    (key.digest,),
                ).fetchone()
                connection.commit()
                return self._reservation(
                    row,
                    state=ConversationBindingState.RESERVED,
                    acquired=True,
                    owner_token=owner_token,
                )
            except Exception:
                connection.rollback()
                raise

    def complete_reservation(
        self,
        key: ConversationBindingKey,
        owner_token: str,
        external_conversation_id: str,
        now: float | None = None,
    ) -> ExternalConversationBinding:
        key = self._validate_key(key)
        owner_token = self._validate_owner(owner_token)
        external_conversation_id = self._validate_external_id(
            external_conversation_id
        )
        current_time = _timestamp(now, "now")

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT binding_key_digest, agent_name, external_runtime, "
                    "external_conversation_id, state, created_at, updated_at, "
                    "version, owner_token, lease_expires_at "
                    "FROM conversation_bindings WHERE binding_key_digest = ?",
                    (key.digest,),
                ).fetchone()
                if row is None:
                    raise ConversationBindingNotFoundError("reservation not found")
                state = ConversationBindingState(row["state"])
                if state is ConversationBindingState.BOUND:
                    raise ConversationBindingAlreadyBoundError(
                        "BOUND binding cannot be overwritten"
                    )
                if float(row["lease_expires_at"]) <= current_time:
                    raise ConversationBindingReservationExpiredError(
                        "reservation lease expired"
                    )
                if not hmac.compare_digest(str(row["owner_token"]), owner_token):
                    raise ConversationBindingOwnerError("reservation owner mismatch")

                connection.execute(
                    "UPDATE conversation_bindings SET state = 'BOUND', "
                    "external_conversation_id = ?, owner_token = NULL, "
                    "lease_expires_at = NULL, updated_at = ? "
                    "WHERE binding_key_digest = ? AND state = 'RESERVED' "
                    "AND owner_token = ?",
                    (
                        external_conversation_id,
                        current_time,
                        key.digest,
                        owner_token,
                    ),
                )
                updated = connection.execute(
                    "SELECT binding_key_digest, agent_name, external_runtime, "
                    "external_conversation_id, state, created_at, updated_at, "
                    "version, owner_token, lease_expires_at "
                    "FROM conversation_bindings WHERE binding_key_digest = ?",
                    (key.digest,),
                ).fetchone()
                connection.commit()
                return self._row_to_binding(updated)
            except Exception:
                connection.rollback()
                raise

    def release_reservation(
        self,
        key: ConversationBindingKey,
        owner_token: str,
        now: float | None = None,
    ) -> bool:
        key = self._validate_key(key)
        owner_token = self._validate_owner(owner_token)
        _timestamp(now, "now")

        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                row = connection.execute(
                    "SELECT state, owner_token FROM conversation_bindings "
                    "WHERE binding_key_digest = ?",
                    (key.digest,),
                ).fetchone()
                if row is None or row["state"] == ConversationBindingState.BOUND.value:
                    connection.commit()
                    return False
                if not hmac.compare_digest(str(row["owner_token"]), owner_token):
                    raise ConversationBindingOwnerError("reservation owner mismatch")
                connection.execute(
                    "DELETE FROM conversation_bindings "
                    "WHERE binding_key_digest = ? AND state = 'RESERVED' "
                    "AND owner_token = ?",
                    (key.digest, owner_token),
                )
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise


__all__ = [
    "BINDING_DIGEST_SCHEMA_VERSION",
    "DEFAULT_BUSY_TIMEOUT_MS",
    "SCHEMA_VERSION",
    "ConversationBindingAlreadyBoundError",
    "ConversationBindingError",
    "ConversationBindingKey",
    "ConversationBindingNotFoundError",
    "ConversationBindingOwnerError",
    "ConversationBindingReservation",
    "ConversationBindingReservationExpiredError",
    "ConversationBindingState",
    "ConversationBindingStore",
    "ConversationIdentity",
    "ExternalConversationBinding",
    "SQLiteConversationBindingStore",
]
