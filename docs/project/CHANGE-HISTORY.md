# Change history

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 960facfea7fe64558bba021a3b5645deda107af8
Supersedes: none
Superseded by: none

## 2026-07-17 - OJ0 local foundation

- Created the D-only project foundation, portable policies, schemas,
  templates, canonical project memory and safe workspace scripts.
- Reserved mobile, contracts and future infrastructure locations.
- Did not download official code, initialize Git, install dependencies,
  create worktrees, access credentials, GitHub or VPS.

## 2026-07-17 - OJ1 fork and root promotion

- Created and validated the Cesar fork, captured the live upstream SHA,
  cloned with blob filtering, configured origin/upstream and promoted the
  clone to the canonical Git root.
- Restored the OJ0 foundation from a verified D: staging backup and added
  only the delimited local-boundaries block to the upstream .gitignore.
- No dependencies, models, services, worktrees, VPS, deploy, migration or
  functional OpenJarvis execution was performed.

## 2026-07-17 - OJ1-H architectural hardening

- Normalized portable policies and canonical documentation metadata against
  the upstream foundation baseline.
- Removed versioned machine-specific paths and retained all project-managed
  storage on disk D through ignored local configuration.
- Kept all four lifecycle scripts disabled as neutral safe stubs and added
  explicit lifecycle policy and state records.
- CI diagnosis was read-only and classified as `INSUFFICIENT_EVIDENCE`:
  Actions permission is enabled, the PR trigger is present, but GitHub
  exposes no workflow inventory or run for this fork branch.
- No upstream functional code or workflow was changed, and no installation,
  model, service, VPS or CodexAgent work was performed.

## 2026-07-17 - OJ2 Codex runtime audit (DRAFT)

- Revalidated the local/origin baseline and live upstream main before auditing
  the runtime, Windows installer, quickstart, storage paths, desktop setup,
  frontend model gate, server streaming and Claude bridge.
- Consulted the official Codex app-server protocol documentation in read-only
  mode and proposed a future stdio JSON-RPC adapter without implementing it.
- Confirmed that the Windows installer installs Ollama and pulls a starter
  model, and that the current runtime is engine/model-first; recorded the
  no-Ollama installation and future PR gates in the DRAFT report.
- No functional code, workflow, dependency, model, credential, service, VPS,
  deploy or merge operation was performed.

## 2026-07-17 - OJ2-V installed Codex contract validation

- Validated the installed `codex-cli 0.144.3` with its stable JSON Schema,
  including initialize/initialized, account/read, model/list, threads, turns,
  approvals, streaming notifications and workspace/sandbox fields.
- Ran one sanitized non-interactive stdio probe: handshake, read-only account
  query with `refreshToken=false` and model catalog query passed; no prompt,
  thread, turn, approval, login, logout or model download occurred.
- Froze the public architecture as first-class agent selection (`agent=codex`),
  with descriptor-driven internal composition and no InferenceEngine
  prerequisite for Codex. ClaudeCodeAgent remains present.
- Updated the OJ2 DRAFT verdict to GO only for PR A — External Agent Contract;
  CodexAgent functionality, UI, installation and default change remain blocked.
- No functional code, workflow, dependency, model, credential, service, VPS,
  deploy, migration, ready-for-review or merge operation was performed.

## 2026-07-17 - OJ2-M human approval and canonicalization

- Human architectural review approved the OJ2/OJ2-V report on 2026-07-17 after
  the required PR #2 checks completed successfully on the validated HEAD.
- Promoted the report and Codex contract memory from DRAFT to CANONICAL.
- Recorded the definitive verdict: OJ2 approved; GO only for PR A — External
  Agent Contract; NO-GO for functional CodexAgent, UI, installation and default
  change.
- Kept thread durability, reconnection, concurrency, final sandbox, telemetry
  and end-to-end integration explicitly unproven. PR A was not implemented in
  the OJ2-M task itself; it was authorized for the subsequent OJ3-A task.

## 2026-07-17 12:46:10 -03:00 - OJ3-A External Agent Contract

- Added immutable `AgentDescriptor` and `AgentExecutionMode` metadata to the
  existing `AgentRegistry`; legacy registrations remain ENGINE-backed.
- Added engine-independent composition for registered EXTERNAL agents, with
  Optional system engine/model fields, capability/audit security without an
  engine wrapper, and an explicit `ENGINE_REQUIRED_FOR_SELECTED_AGENT` error.
- Added deterministic fake-external contract tests. No CodexAgent, app-server,
  subprocess, UI, installation, dependency, model, workflow, default or
  credential change was made.
- OJ3-A was integrated by squash merge as
  `7ff9dbebfb36c74073795ba96b83aa84db7a741e`; its task branch was removed.

## 2026-07-17 15:26:44 -03:00 - OJ3-B Codex app-server client core

- Added a stdlib-only, explicitly-started Codex app-server JSONL client with
  typed lifecycle, request correlation, notifications, fail-closed server
  request handling and sanitized account/model reads.
- Added a temporary-process fake app-server test suite; no real Codex process,
  prompt, conversation thread, turn, login/logout, model download or network
  operation is used by the tests.
- Kept `CodexAgent`, `AgentRegistry`, `SystemBuilder`, UI, workflows,
  installers, defaults and runtime connection unchanged.
- Preserved the primary protocol error on malformed stdout, aligned the two
  new modules with Ruff, and completed final CI run `29603505953` successfully
  across lint/format, Linux, Rust and Windows 3.12/3.13.
- Left PR #4 open as draft at
  `960facfea7fe64558bba021a3b5645deda107af8`; no ready-for-review or merge
  operation was performed.
