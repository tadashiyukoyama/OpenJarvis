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

Current state: NOT_IMPLEMENTED. OJ2 completed a static audit and recorded its
findings as DRAFT in
`docs/project/research/OJ2-CODEX-RUNTIME-AUDIT.md`.

The future implementation must preserve authentication, session state,
streaming, approvals and workspace context. The audit verified that the
current OpenJarvis composition is engine/model-first, so a Codex path cannot be
added safely by only registering another `BaseAgent`. The proposed transport is
the installed Codex app-server over local stdio JSON-RPC, but this proposal is
not yet canonical and no implementation is authorized.

Study the existing Claude Code integration as a reference, but do not copy it
without an audit of the official code. The CodexAgent remains unimplemented.
