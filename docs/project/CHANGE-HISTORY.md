# Change history

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
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
