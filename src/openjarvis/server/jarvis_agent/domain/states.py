"""Finite states used by the Jarvis agent boundary."""

from __future__ import annotations

from enum import Enum


class SessionState(str, Enum):
    OPENING = "OPENING"
    ACTIVE = "ACTIVE"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    FAILED = "FAILED"


class ActionState(str, Enum):
    PROPOSED = "PROPOSED"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPROVED = "APPROVED"
    DISPATCHING = "DISPATCHING"
    ACCEPTED = "ACCEPTED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"
    BUSY = "BUSY"
    UNKNOWN = "UNKNOWN"


class JobState(str, Enum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    BUSY = "BUSY"
    CANCELLED = "CANCELLED"
    UNKNOWN = "UNKNOWN"


class EdgeJobState(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"
    UNKNOWN = "UNKNOWN"


class Effect(str, Enum):
    READ = "READ"
    MUTATION = "MUTATION"
    DELEGATION = "DELEGATION"


TERMINAL_ACTION_STATES = frozenset(
    {
        ActionState.COMPLETED,
        ActionState.DENIED,
        ActionState.CANCELLED,
        ActionState.EXPIRED,
        ActionState.FAILED,
        ActionState.BUSY,
        ActionState.UNKNOWN,
    }
)

TERMINAL_JOB_STATES = frozenset(
    {
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.BUSY,
        JobState.CANCELLED,
        JobState.UNKNOWN,
    }
)

TERMINAL_EDGE_JOB_STATES = frozenset(
    {
        EdgeJobState.SUCCEEDED,
        EdgeJobState.FAILED,
        EdgeJobState.CANCELLED,
        EdgeJobState.EXPIRED,
        EdgeJobState.UNKNOWN,
    }
)
