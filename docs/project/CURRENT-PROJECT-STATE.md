# Current project state

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 5c719de2da9c2f43a46bdf598a3f6d982cd28807
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
| originMainSha | 5c719de2da9c2f43a46bdf598a3f6d982cd28807 |
| upstreamMainSha | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| activeBranch | feat/external-agent-contract |
| dependenciesInstalled | false |
| modelsDownloaded | false |
| codexAgentIntegration | EXTERNAL_AGENT_CONTRACT_IMPLEMENTED; CodexAgent NOT_IMPLEMENTED |
| codexVersionValidated | 0.144.3 |
| codexAppServerValidation | PASS: stable schema, stdio handshake, sanitized account/model reads |
| pullRequest | OJ3-A draft PR — External Agent Contract; CI pending at commit |
| lifecycleAutomation | DISABLED |
| ci | OJ3-A draft checks pending at commit; local pytest unavailable |
| mobileRepository | UNVERIFIED |
| mobileImplementation | NOT_STARTED |
| vps | NOT_CONTRACTED |
| deploy | NOT_STARTED |
| additionalWorktrees | 0 |

Evidence (2026-07-17 12:46:10 -03:00): OJ2-M revalidated the local baseline, origin/main and upstream main
live with 40-character refs before approval. The audit branch contains
documentation-only changes plus ignored local schema/probe evidence. The
installed `codex-cli 0.144.3` generated a stable schema; a non-interactive
stdio probe approved handshake, `account/read(refreshToken=false)` and
`model/list`, then exited without an orphan. OJ3-A adds only immutable agent
descriptors, agent-first engine/model composition, Optional system dependencies,
explicit engine-required errors and deterministic fake-external tests. No
functional CodexAgent, workflow, dependency, model or service was added.

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

Current blockers: thread persistence, streaming/approval UX, sandbox policy,
production telemetry/concurrency behavior, end-to-end behavior and D-only
no-Ollama installation remain unimplemented or unproven for production.
Dependency installation, models, login, UI, default change and later phases
remain unauthorized. OJ3-A is the authorized PR A contract scope; its draft
PR has its own CI/review gate.

OJ2/OJ2-V report: `docs/project/research/OJ2-CODEX-RUNTIME-AUDIT.md` (CANONICAL).

Human architectural review: approved on 2026-07-17. OJ2 is approved with GO
only for PR A — External Agent Contract. OJ3-A is draft and stops after CI;
threads, reconnection, concurrency, final sandbox, telemetry and end-to-end
integration remain unproven; OJ3-A does not implement CodexAgent.
