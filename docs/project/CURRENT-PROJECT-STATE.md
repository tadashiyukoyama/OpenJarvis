# Current project state

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
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
| originMainSha | e57ac00b1f98b6b9e9db60145b838a5507e2c5fb |
| upstreamMainSha | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| activeBranch | main |
| dependenciesInstalled | false |
| modelsDownloaded | false |
| codexAgentIntegration | NOT_IMPLEMENTED |
| codexVersionValidated | 0.144.3 |
| codexAppServerValidation | PASS: stable schema, stdio handshake, sanitized account/model reads |
| pullRequest | #2 MERGED — OJ2/OJ2-V squash |
| lifecycleAutomation | DISABLED |
| ci | INSUFFICIENT_EVIDENCE |
| mobileRepository | UNVERIFIED |
| mobileImplementation | NOT_STARTED |
| vps | NOT_CONTRACTED |
| deploy | NOT_STARTED |
| additionalWorktrees | 0 |

Evidence: OJ2-M revalidated the local baseline, origin/main and upstream main
live with 40-character refs before approval. The audit branch contains
documentation-only changes plus ignored local schema/probe evidence. The
installed `codex-cli 0.144.3` generated a stable schema; a non-interactive
stdio probe approved handshake, `account/read(refreshToken=false)` and
`model/list`, then exited without an orphan. No functional code, workflow,
dependency, model or service was changed.

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

Current blockers: the engine-independent agent contract, thread persistence,
streaming/approval UX, sandbox policy, end-to-end behavior and D-only
no-Ollama installation remain unimplemented or unproven for production.
Dependency installation, models, login, UI, default change and later phases
remain unauthorized. The only possible future implementation scope identified
by OJ2-V is PR A — External Agent Contract, requiring its own authorization.

OJ2/OJ2-V report: `docs/project/research/OJ2-CODEX-RUNTIME-AUDIT.md` (CANONICAL).

Human architectural review: approved on 2026-07-17. OJ2 is approved with GO
only for PR A — External Agent Contract. Threads, reconnection, concurrency,
final sandbox, telemetry and end-to-end integration remain unproven; PR A does
not implement CodexAgent.
