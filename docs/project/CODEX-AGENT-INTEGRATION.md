# Codex agent integration

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 960facfea7fe64558bba021a3b5645deda107af8
Supersedes: none
Superseded by: none

Requirement:

OpenJarvis must offer Codex as a first-class selectable external agent, at the
same architectural level as `claude_code`, `opencode`, `simple`,
`orchestrator` and `react`. The public selection remains selection of an agent:

```toml
[agent]
default_agent = "codex"
```

Codex is not an `InferenceEngine`, not a local-model provider and not a public
runtime→agent two-step experience. A selector may exist only internally while
composing the selected agent from its descriptor.

Current state: the engine-independent External Agent Contract is merged in
OJ3-A; OJ3-B implements an isolated `CodexAppServerClient` transport core on a
draft PR with final CI PASS; `CodexAgent` remains NOT_IMPLEMENTED. OJ2 is CANONICAL after human
architectural review approved on 2026-07-17. OJ2-V validated `codex-cli 0.144.3` locally:
the stable schema was generated without `--experimental`; the stdio handshake,
sanitized account read and model catalog read passed; no thread, turn, prompt,
approval, login or logout was executed. Evidence is local and ignored under
`.workspace/local/audit/`.

The future `AgentRegistry` descriptor is:

| Field | Codex value |
|---|---|
| `name` | `codex` |
| `execution_mode` | `external` |
| `requires_engine` | `false` |
| `requires_model` | `false` |
| `external_runtime` | `codex_app_server` |

`SystemBuilder` must resolve the selected agent before resolving an engine.
Engine-backed agents continue to resolve engine, model and health as today.
`CodexAgent` must not call `_resolve_engine()`, `_resolve_model()`,
`engine.health()`, `engine.list_models()`, Ollama discovery or local-engine
fallback. The future adapter must preserve Codex-managed authentication,
threads, streaming, approvals, interrupt, sandbox and D-workspace context.

The transport contract is a long-lived local `codex app-server` over stdio
JSON-RPC, isolated behind `CodexAppServerClient`. `ClaudeCodeAgent` remains in
the project and is neither removed nor renamed.

OJ3-A implements only PR A — External Agent Contract: immutable agent metadata,
engine-independent composition and fake-external tests. OJ3-B adds only the
explicitly-started, stdlib JSONL process client with sanitized handshake,
account/model read wrappers and fake-process tests. It remains disconnected
from the runtime and does not implement a CodexAgent, UI, authentication,
Ollama, model selection/download, installation or default change. The draft PR
remains subject to its own CI/review gate.
