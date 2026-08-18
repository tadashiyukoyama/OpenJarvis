"""SQLite schema managed locally by the Jarvis agent core."""

from __future__ import annotations

SCHEMA_VERSION = 4

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS jarvis_agent_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS jarvis_sessions (
    session_id TEXT PRIMARY KEY,
    generation INTEGER NOT NULL CHECK (generation > 0),
    project_key TEXT NOT NULL,
    codex_thread_id TEXT NOT NULL DEFAULT '',
    manifest_version TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    closed_at REAL
);

CREATE TABLE IF NOT EXISTS jarvis_turns (
    turn_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES jarvis_sessions(session_id),
    generation INTEGER NOT NULL,
    transcript_text TEXT,
    transcript_hash TEXT NOT NULL,
    committed_at REAL NOT NULL,
    redacted_at REAL
);
CREATE INDEX IF NOT EXISTS idx_jarvis_turns_session
    ON jarvis_turns(session_id, committed_at);

CREATE TABLE IF NOT EXISTS jarvis_actions (
    action_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES jarvis_sessions(session_id),
    generation INTEGER NOT NULL,
    function_call_id TEXT NOT NULL,
    tool_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    payload_json TEXT,
    preview_json TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL,
    updated_at REAL NOT NULL,
    result_json TEXT,
    result_summary TEXT NOT NULL DEFAULT '',
    error_code TEXT,
    UNIQUE(session_id, function_call_id, payload_hash)
);
CREATE INDEX IF NOT EXISTS idx_jarvis_actions_session
    ON jarvis_actions(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_jarvis_actions_state
    ON jarvis_actions(state, expires_at);

CREATE TABLE IF NOT EXISTS jarvis_approvals (
    approval_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE REFERENCES jarvis_actions(action_id),
    session_id TEXT NOT NULL,
    function_call_id TEXT NOT NULL,
    payload_hash TEXT NOT NULL,
    decision TEXT NOT NULL,
    decided_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS jarvis_jobs (
    job_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL UNIQUE REFERENCES jarvis_actions(action_id),
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    result_json TEXT,
    result_summary TEXT NOT NULL DEFAULT '',
    error_code TEXT
);
CREATE INDEX IF NOT EXISTS idx_jarvis_jobs_state
    ON jarvis_jobs(state, updated_at);

CREATE TABLE IF NOT EXISTS jarvis_context (
    partition_key TEXT PRIMARY KEY,
    project_key TEXT NOT NULL,
    codex_thread_id TEXT NOT NULL DEFAULT '',
    context_json TEXT NOT NULL,
    updated_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jarvis_context_expiry
    ON jarvis_context(expires_at);

CREATE TABLE IF NOT EXISTS jarvis_references (
    reference_id TEXT PRIMARY KEY,
    partition_key TEXT NOT NULL,
    source TEXT NOT NULL,
    kind TEXT NOT NULL,
    value_hash TEXT NOT NULL,
    provider_value TEXT NOT NULL,
    metadata_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL,
    UNIQUE(partition_key, source, kind, value_hash)
);
CREATE INDEX IF NOT EXISTS idx_jarvis_references_expiry
    ON jarvis_references(expires_at);

CREATE TABLE IF NOT EXISTS jarvis_agent_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    event_type TEXT NOT NULL,
    session_id TEXT,
    action_id TEXT,
    job_id TEXT,
    payload_json TEXT NOT NULL,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jarvis_events_session
    ON jarvis_agent_events(session_id, sequence);

CREATE TABLE IF NOT EXISTS jarvis_external_operations (
    action_id TEXT PRIMARY KEY REFERENCES jarvis_actions(action_id),
    provider TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    state TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    last_sequence INTEGER,
    UNIQUE(provider, resource_type, resource_id)
);
CREATE INDEX IF NOT EXISTS idx_jarvis_external_resource
    ON jarvis_external_operations(provider, resource_type, resource_id);

CREATE TABLE IF NOT EXISTS jarvis_provider_events (
    delivery_id TEXT PRIMARY KEY,
    event_id TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL,
    event_name TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    resource_sequence INTEGER NOT NULL,
    resource_version TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    received_at REAL NOT NULL,
    disposition TEXT NOT NULL,
    action_id TEXT REFERENCES jarvis_actions(action_id)
);
CREATE INDEX IF NOT EXISTS idx_jarvis_provider_events_resource
    ON jarvis_provider_events(provider, resource_type, resource_id, resource_sequence);

CREATE TABLE IF NOT EXISTS jarvis_provider_event_outcomes (
    event_id TEXT PRIMARY KEY REFERENCES jarvis_provider_events(event_id),
    next_state TEXT NOT NULL,
    result_json TEXT NOT NULL,
    result_summary TEXT NOT NULL,
    error_code TEXT
);

CREATE TABLE IF NOT EXISTS jarvis_provider_sequences (
    provider TEXT NOT NULL,
    resource_type TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    last_sequence INTEGER NOT NULL,
    resource_version TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY(provider, resource_type, resource_id)
);
"""
