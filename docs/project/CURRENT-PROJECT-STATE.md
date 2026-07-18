# Current project state

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Functional implementation commit: `91e4330` (OJ3-C primary commit)
Current live PR head/checks: confirm on GitHub after push; not asserted here.
Supersedes: none
Superseded by: none

| Field | Value |
|---|---|
| workspaceRoot | OPENJARVIS_WORKSPACE_ROOT |
| workspaceFoundation | ESTABLISHED |
| gitRootCanonical | OPENJARVIS_WORKSPACE_ROOT |
| officialUpstream | open-jarvis/OpenJarvis |
| officialCodeDownloaded | true |
| originFork | tadashiyukoyama/OpenJarvis |
| originMainSha | f37bb5bad35a6ee21ac9920b462f09f24cae5476 |
| upstreamMainSha | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| activeBranch | feat/codex-conversation-runtime-core |
| dependenciesInstalled | false |
| modelsDownloaded | false |
| codexAgentIntegration | EXTERNAL_AGENT_CONTRACT_MERGED; CODEX_APP_SERVER_CLIENT_CORE_MERGED; CODEX_CONVERSATION_RUNTIME_CORE_HARDENED_DRAFT; CodexAgent NOT_IMPLEMENTED |
| codexVersionValidated | 0.144.3 |
| codexAppServerValidation | PASS: stable schema, stdio handshake, sanitized account/model reads |
| pullRequest | PR #4 MERGED by squash as `f37bb5bad35a6ee21ac9920b462f09f24cae5476`; PR #5 remains OPEN and draft for OJ3-C-H |
| lifecycleAutomation | DISABLED |
| ci | PR #4 final CI `29608853924` PASS; OJ3-C-H local stubbed unittest, compile and fake harness PASS; local pytest and Ruff unavailable; new PR #5 CI pending |
| mobileRepository | UNVERIFIED |
| mobileImplementation | NOT_STARTED |
| vps | NOT_CONTRACTED |
| deploy | NOT_STARTED |
| additionalWorktrees | 0 |

Evidence (2026-07-17 14:34:44 -03:00): OJ3-A-M revalidated PR #3, merged it by
squash as `7ff9dbebfb36c74073795ba96b83aa84db7a741e`, synchronized `main`,
removed the PR branch and retained one canonical worktree. OJ3-B adds only a
stdlib Codex app-server JSONL transport client and deterministic fake-process
tests. It is not connected to `CodexAgent`, `AgentRegistry`, `SystemBuilder`,
the UI or the OpenJarvis runtime. No prompt, conversation thread, turn,
approval UX, login/logout, model download or credential transfer was added.

Evidence (2026-07-17 15:26:44 -03:00, historical): OJ3-B pre-hardening was an
open draft PR #4 based on the merged main SHA
`7ff9dbebfb36c74073795ba96b83aa84db7a741e`; historical CI run `29603505953`
passed lint/format, Linux tests, Rust, Windows 3.12 and Windows 3.13. That
run is not the OJ3-B-H gate.

Evidence (2026-07-17 17:12:03 -03:00): OJ3-B-H was integrated through PR #4
with squash merge `f37bb5bad35a6ee21ac9920b462f09f24cae5476`; local `main` and
`origin/main` were synchronized, the integrated branch was removed, and one
worktree remains. OJ3-C primary commit `91e4330` adds only the conversation
runtime core over an already-ready client. Its live draft PR head and checks
must be confirmed on GitHub.

Evidence (2026-07-17 19:35:36 -03:00): OJ3-C-H corrected the conversation
runtime wait loop, bounded timeout/close behavior, multi-waiter release,
public final-text reconciliation and completed-turn retention. The local
deterministic suite passed 19 unittest cases plus the fake-process harness;
validation used a temporary namespace stub because project dependencies are
not installed. The new PR #5 CI run remains the final remote gate.

OJ1-H completed the portability and lifecycle-policy correction. The four
lifecycle scripts remain safe stubs and do not mutate Git or the filesystem.
The fork CI has no execution recorded. Actions permission is enabled, but the
GitHub workflow inventory is empty even though `ci.yml` is present and
configured locally for pull requests to `main`; the read-only evidence is
insufficient to establish a runnable workflow. No installation, model,
service, VPS or CodexAgent work was performed. The public architecture is
agent-first: future selection is `agent=codex`, while any engine decision is
internal and descriptor-driven. `CodexAgent` is not an InferenceEngine and is
not implemented.

Current blockers: persistent OpenJarvis-Codex thread identity, approvals UX,
production telemetry/concurrency behavior, end-to-end behavior and D-only
no-Ollama installation remain unimplemented or unproven for production. The
conversation runtime intentionally does not add HTTP/SSE, frontend/Tauri,
login/logout, installation, Ollama, model download or a default change.
Dependency installation, models, login, UI, default change and later phases
remain unauthorized. OJ3-C-H is limited to the conversation runtime draft PR
and stops after its new CI gate.

OJ2/OJ2-V report: `docs/project/research/OJ2-CODEX-RUNTIME-AUDIT.md` (CANONICAL).

Human architectural review: approved on 2026-07-17. OJ2 is approved with GO
only for PR A — External Agent Contract. OJ3-A and OJ3-B are merged; OJ3-C-H
is draft and stopped pending its new CI gate. Persistent identity,
reconnection, production concurrency, approvals UX, telemetry and end-to-end
integration remain unproven; `CodexAgent` is not implemented.
