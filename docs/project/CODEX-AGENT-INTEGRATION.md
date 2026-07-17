# Codex agent integration

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

Requirement:

OpenJarvis must offer Codex as a selectable external agent without requiring
a local model or OPENAI_API_KEY for that mode.

Initial state: NOT_IMPLEMENTED.

The future implementation must preserve authentication, session state,
streaming, approvals and workspace context. No implementation is authorized
before the OJ2 audit. Study the existing Claude Code integration as a
reference, but do not copy it without an audit of the official code. The
CodexAgent remains unimplemented.
