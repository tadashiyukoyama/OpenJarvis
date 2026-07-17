# Architecture map

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

OJ2 audited the current runtime boundaries without changing functional code.
The official OpenJarvis components are present at the captured SHA. The
Codex-specific architecture below is a DRAFT proposal and is not an
implementation authorization.

| Area | Verified OJ2 state |
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

| Runtime composition | `SystemBuilder` resolves a healthy inference engine and model before constructing `JarvisSystem`. |
| External agent boundary | `ClaudeCodeAgent` is a Python→Node subprocess bridge and is not a Codex contract. |
| Desktop startup | Tauri reports Ollama/model/server readiness and can run `uv sync`; this is not a no-Ollama Codex path. |
| Chat transport | Backend exposes OpenAI-compatible HTTP/SSE; agent streaming is bridged from synchronous execution. |
| Runtime state | `OPENJARVIS_HOME` can relocate state, but the fallback is `Path.home()/.openjarvis`; D-only installation must set and verify it. |
| Codex proposal | Future selectable provider using a local `codex app-server` over stdio JSON-RPC; DRAFT only. |

Detailed evidence and the no-Ollama installation proposal are in
`docs/project/research/OJ2-CODEX-RUNTIME-AUDIT.md`.
