"""Schema owned by the outbound Edge Worker boundary."""

from __future__ import annotations

EDGE_SCHEMA_VERSION = 1

EDGE_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS jarvis_edge_devices (
    device_id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    revoked INTEGER NOT NULL DEFAULT 0 CHECK (revoked IN (0, 1)),
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    current_credential_fingerprint TEXT NOT NULL DEFAULT '',
    previous_credential_fingerprint TEXT NOT NULL DEFAULT '',
    previous_credential_expires_at REAL,
    connected_at REAL,
    last_seen_at REAL,
    disconnected_at REAL,
    last_error_code TEXT,
    updated_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jarvis_edge_devices_status
    ON jarvis_edge_devices(status, revoked, last_seen_at);

CREATE TABLE IF NOT EXISTS jarvis_edge_sequences (
    device_id TEXT PRIMARY KEY REFERENCES jarvis_edge_devices(device_id),
    inbound_sequence INTEGER NOT NULL DEFAULT 0,
    outbound_sequence INTEGER NOT NULL DEFAULT 0,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS jarvis_edge_assignments (
    job_id TEXT PRIMARY KEY,
    action_id TEXT,
    device_id TEXT NOT NULL REFERENCES jarvis_edge_devices(device_id),
    attempt_id TEXT NOT NULL UNIQUE,
    attempt_number INTEGER NOT NULL CHECK (attempt_number > 0),
    tool_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    state TEXT NOT NULL,
    offered_at REAL NOT NULL,
    accepted_at REAL,
    lease_expires_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    terminal_event_id TEXT,
    result_json TEXT,
    result_summary TEXT NOT NULL DEFAULT '',
    error_code TEXT,
    sensitive_purge_at REAL
);
CREATE INDEX IF NOT EXISTS idx_jarvis_edge_assignments_device_state
    ON jarvis_edge_assignments(device_id, state, updated_at);
CREATE INDEX IF NOT EXISTS idx_jarvis_edge_assignments_action
    ON jarvis_edge_assignments(action_id);

CREATE TABLE IF NOT EXISTS jarvis_edge_attempts (
    attempt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jarvis_edge_assignments(job_id),
    device_id TEXT NOT NULL REFERENCES jarvis_edge_devices(device_id),
    attempt_number INTEGER NOT NULL,
    state TEXT NOT NULL,
    lease_expires_at REAL NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    UNIQUE(job_id, attempt_number)
);

CREATE TABLE IF NOT EXISTS jarvis_edge_events (
    event_id TEXT PRIMARY KEY,
    device_id TEXT NOT NULL REFERENCES jarvis_edge_devices(device_id),
    direction TEXT NOT NULL CHECK (direction IN ('inbound', 'outbound')),
    sequence INTEGER NOT NULL,
    event_type TEXT NOT NULL,
    job_id TEXT,
    payload_hash TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    occurred_at TEXT NOT NULL,
    received_at REAL NOT NULL,
    UNIQUE(device_id, direction, sequence)
);
CREATE INDEX IF NOT EXISTS idx_jarvis_edge_events_retention
    ON jarvis_edge_events(received_at, direction);
CREATE INDEX IF NOT EXISTS idx_jarvis_edge_events_job
    ON jarvis_edge_events(job_id, received_at);

CREATE TABLE IF NOT EXISTS jarvis_edge_approvals (
    approval_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jarvis_edge_assignments(job_id),
    attempt_id TEXT NOT NULL REFERENCES jarvis_edge_attempts(attempt_id),
    state TEXT NOT NULL,
    preview_json TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    decided_at REAL,
    decision TEXT
);
CREATE INDEX IF NOT EXISTS idx_jarvis_edge_approvals_state
    ON jarvis_edge_approvals(state, expires_at);
"""


__all__ = ["EDGE_SCHEMA_SQL", "EDGE_SCHEMA_VERSION"]
