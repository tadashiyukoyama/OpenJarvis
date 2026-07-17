# Architecture map

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 7ff9dbebfb36c74073795ba96b83aa84db7a741e
Supersedes: none
Superseded by: none

OJ2-V validated the installed Codex app-server boundary. OJ3-A merged the
engine-independent External Agent Contract, and OJ3-B implements an isolated
stdlib transport client on a draft PR. The official OpenJarvis components are
present at the captured SHA; `CodexAgent` implementation, UI and default
change remain unauthorized.

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
| Runtime state | `OPENJARVIS_HOME` can relocate state, but the fallback is `Path.home()/.openjarvis`; D-only installation must set and verify it. |
| Codex boundary | Future `CodexAgent` → `CodexAppServerClient` → local `codex app-server` over stdio JSON-RPC; no `InferenceEngine` prerequisite. |
| Internal selector | `RuntimeSelector`, if needed, is an internal composition detail based on the descriptor, never a public runtime→agent selector. |
| Local validation | Codex `0.144.3` stable schema, handshake, sanitized `account/read` and `model/list` passed; OJ3-B fake-process transport validation passed; runtime connection remains absent. |

For engine-backed agents, the current engine/model/health/list-model behavior
remains. For registered EXTERNAL agents, composition represents engine/model as
absent and does not provide engine-dependent tools or local inference
telemetry. For `CodexAgent`, composition must not call `_resolve_engine()`,
`_resolve_model()`, `engine.health()`, `engine.list_models()`, Ollama discovery
or local-engine fallback. `ClaudeCodeAgent` remains unchanged in name and
availability. Codex becomes a future default only after end-to-end tests and
explicit authorization.

Detailed evidence and the no-Ollama installation proposal are in
`docs/project/research/OJ2-CODEX-RUNTIME-AUDIT.md`.
