# Codex agent integration

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-18
Functional implementation commit: OJ5-A draft branch; SHA recorded in the task report
Current main base: `d487c428a48f50163ba4fb08387e3545ee6607a3`
Current draft PR head/checks: confirm on GitHub after push; not asserted here.
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
OJ3-A; OJ3-B-H hardens an isolated `CodexAppServerClient` transport core and
PR #4 was integrated by squash as
`f37bb5bad35a6ee21ac9920b462f09f24cae5476`. OJ3-C adds only the
`CodexConversationRuntime` over an already-ready client in primary commit
`91e4330`; its draft PR live head/checks must be confirmed on GitHub.
`CodexAgent` remains NOT_IMPLEMENTED. OJ2 is CANONICAL after human
architectural review approved on 2026-07-17. OJ2-V validated `codex-cli 0.144.3` locally:
the stable schema was generated without `--experimental`; the stdio handshake,
sanitized account read and model catalog read passed; no thread, turn, prompt,
approval, login or logout was executed. Evidence is local and ignored under
`.workspace/local/audit/`.

OJ4-A Actions governance is integrated in `main` at
`d487c428a48f50163ba4fb08387e3545ee6607a3`. OJ5-A defines a provider-neutral
persistent identity contract in a draft PR: `ConversationIdentity` and a
versioned SHA-256 `ConversationBindingKey` are backed by an explicitly injected
SQLite store with atomic `RESERVED`/`BOUND` transitions and leases. The
optional `AgentContext.conversation_identity` carrier is compatible with
existing constructors. No HTTP/SSE route, UI, `CodexAgent`, registry entry,
builder wiring or real Codex conversation consumes this identity yet.

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
JSON-RPC, isolated behind `CodexAppServerClient`. The conversation runtime
adds stable thread/turn contracts, sanitized event routing, public text
aggregation, interruption and bounded waiting without owning that client.
`ClaudeCodeAgent` remains in the project and is neither removed nor renamed.

OJ3-A implements only PR A — External Agent Contract: immutable agent metadata,
engine-independent composition and fake-external tests. OJ3-B-H adds only
hardening to the explicitly-started, stdlib JSONL process client: per-generation
lifecycle isolation, fatal protocol shutdown, safe server-response serialization,
concurrent-close behavior and fake-process tests; that scope is merged in PR #4.
OJ3-C adds only stable conversation DTOs, subscriptions, thread/turn lifecycle,
public event aggregation, timeout/interruption and fake app-server tests. It
does not implement `CodexAgent`, provider propagation or real thread execution,
approvals UX, HTTP, SSE, frontend, Tauri, authentication, Ollama, model
selection/download, installation or a default change. The C PR was integrated
before OJ4-A; the OJ5-A PR remains draft and subject to its architectural
review gate.

OJ3-C-H hardens only the conversation runtime: `wait_turn` performs bounded
condition waits inside its state loop, close and client failure release all
waiters, terminal events release multiple waiters, public final text is
reconciled without duplication, reasoning remains non-public, and completed
turn retention skips states with active waiters. Validation uses deterministic
threading events, bounded joins and the existing fake app-server; no
CodexAgent, prompt, real conversation, model, installation or later-phase
integration is included.
