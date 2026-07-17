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
| activeBranch | audit/openjarvis-codex-runtime |
| dependenciesInstalled | false |
| modelsDownloaded | false |
| codexAgentIntegration | NOT_IMPLEMENTED |
| pullRequest | OJ2 draft PR pending creation |
| lifecycleAutomation | DISABLED |
| ci | INSUFFICIENT_EVIDENCE |
| mobileRepository | UNVERIFIED |
| mobileImplementation | NOT_STARTED |
| vps | NOT_CONTRACTED |
| deploy | NOT_STARTED |
| additionalWorktrees | 0 |

Evidence: OJ2 revalidated the local baseline, origin/main and upstream main
live with 40-character refs before the audit. The audit branch starts at the
local/origin baseline and contains documentation-only changes. No functional
code, workflow, dependency, model or service was executed or changed.

OJ1-H completed the portability and lifecycle-policy correction. The four
lifecycle scripts remain safe stubs and do not mutate Git or the filesystem.
The fork CI has no execution recorded. Actions permission is enabled, but the
GitHub workflow inventory is empty even though `ci.yml` is present and
configured locally for pull requests to `main`; the read-only evidence is
insufficient to establish a runnable workflow. No installation, model,
service, VPS or CodexAgent work was performed. OJ2 is not authorized.

Current blockers: the Codex app-server account state, versioned protocol
compatibility, engine-independent runtime contract, thread persistence,
streaming/approval UX and D-only no-Ollama installation remain unproven for
implementation. Dependency installation, execution, models, login and later
phases remain unauthorized.

OJ2 report: `docs/project/research/OJ2-CODEX-RUNTIME-AUDIT.md` (DRAFT).
