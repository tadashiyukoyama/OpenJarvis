# Architecture map

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-18
Functional implementation commit: OJ5-A draft branch; SHA recorded in the task report
Current main base: `d487c428a48f50163ba4fb08387e3545ee6607a3`
Current draft PR head/checks: confirm on GitHub after push; not asserted here.
Supersedes: none
Superseded by: none

OJ2-V validated the installed Codex app-server boundary. OJ3-A, OJ3-B and
OJ3-C were integrated through PRs #4 and #5. OJ4-A added Actions governance
and was integrated through PR #6 by squash as
`d487c428a48f50163ba4fb08387e3545ee6607a3`. OJ5-A now adds only the
provider-neutral persistent conversation identity contract on a draft branch;
`CodexAgent`, its registry wiring, UI and default change remain unauthorized.

| Area | Verified project state |
|---|---|
| Canonical Git root | OPENJARVIS_WORKSPACE_ROOT |
| Official OpenJarvis source | Checked out at captured SHA |
| Project memory | docs/project |
| Portable identity and policies | .workspace |
| Machine-local state | .workspace/local |
| Private material | .private |
| Runtime state | .runtime |
| Reproducible artifacts | .artifacts |
| Mobile reservation | apps/mobile |
| Shared contracts | contracts |
| Future infrastructure | infra |
| Workspace automation | scripts/workspace |

| Runtime composition | `SystemBuilder` resolves the selected `AgentDescriptor` first, then resolves engine/model only for ENGINE agents. |
| Public agent selection | The public selector remains “Agente”; the future contract is `[agent] default_agent = "codex"`. |
| Agent registry metadata | Codex descriptor: `execution_mode=external`, `requires_engine=false`, `requires_model=false`, `external_runtime=codex_app_server`. |
| Composition order | Resolve `AgentDescriptor` first; resolve engine/model only for engine-backed agents. |
| External agent boundary | `ClaudeCodeAgent` is a Python→Node subprocess bridge and is not a Codex contract. |
| Desktop startup | Tauri reports Ollama/model/server readiness and can run `uv sync`; this is not a no-Ollama Codex path. |
| Chat transport | Backend exposes OpenAI-compatible HTTP/SSE; agent streaming is bridged from synchronous execution. |
| Runtime state | Existing runtime stores remain separate; OJ5-A's binding store accepts an explicitly injected database path and never derives one from cwd or `Path.home()`. |
| Conversation identity | `ConversationIdentity` carries internal `conversation_id` and `scope_id`; `ConversationBindingKey` hashes a versioned canonical tuple, and `SQLiteConversationBindingStore` reserves external bindings with leases. |
| Agent context | `AgentContext` can carry an optional provider-neutral identity; `QueryOrchestrator` does not populate it and no end-to-end propagation is claimed. |
| Codex boundary | `CodexConversationRuntime` → caller-owned `CodexAppServerClient` → local `codex app-server` over stdio JSON-RPC; no `InferenceEngine` prerequisite and no `CodexAgent` registration. |
| Internal selector | `RuntimeSelector`, if needed, is an internal composition detail based on the descriptor, never a public runtime→agent selector. |
| Local validation | Codex `0.144.3` stable schema, handshake, sanitized `account/read` and `model/list` passed; OJ3-B fake-process transport and OJ3-C fake conversation runtime validation passed; no real Codex prompt was sent. |

For engine-backed agents, the current engine/model/health/list-model behavior
remains. For registered EXTERNAL agents, composition represents engine/model as
absent and does not provide engine-dependent tools or local inference
telemetry. For `CodexAgent`, composition must not call `_resolve_engine()`,
`_resolve_model()`, `engine.health()`, `engine.list_models()`, Ollama discovery
or local-engine fallback. `ClaudeCodeAgent` remains unchanged in name and
availability. OJ3-C does not add persistent OpenJarvis-Codex identity,
approvals, HTTP/SSE, frontend/Tauri, login/logout, installation, Ollama or a
default change. Codex becomes a future default only after end-to-end tests and
explicit authorization.

OJ5-A does not connect the identity contract to HTTP, SSE, `CodexAgent`,
`AgentRegistry`, `SystemBuilder` or a real external thread.

Detailed evidence and the no-Ollama installation proposal are in
`docs/project/research/OJ2-CODEX-RUNTIME-AUDIT.md`.
