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
| originMainSha | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| upstreamMainSha | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| activeBranch | ops/openjarvis-workspace-foundation |
| dependenciesInstalled | false |
| modelsDownloaded | false |
| codexAgentIntegration | NOT_IMPLEMENTED |
| mobileRepository | UNVERIFIED |
| mobileImplementation | NOT_STARTED |
| vps | NOT_CONTRACTED |
| deploy | NOT_STARTED |
| additionalWorktrees | 0 |

Evidence: OJ1 captured upstream main live with git ls-remote and verified the
same 40-character SHA in origin/main and upstream/main. The partial clone was
promoted to the canonical root and the OJ0 foundation was restored from a
verified D: staging backup. No functional code was changed.

Current blockers: upstream architecture, mobile source and VPS remain
unaudited or unverified by design. Dependency installation, execution,
models and later phases remain unauthorized.
