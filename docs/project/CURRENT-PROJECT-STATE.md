# Current project state

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Functional implementation commit: `523ebb18a805c2dad1cf03fb7649ae27ebbd02f1`
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
| originMainSha | 7ff9dbebfb36c74073795ba96b83aa84db7a741e |
| upstreamMainSha | 3000116d181eb69737241c09eaa70d4c65eb80a0 |
| activeBranch | feat/codex-app-server-client-core |
| dependenciesInstalled | false |
| modelsDownloaded | false |
| codexAgentIntegration | EXTERNAL_AGENT_CONTRACT_MERGED; CODEX_APP_SERVER_CLIENT_CORE_IMPLEMENTED; CodexAgent NOT_IMPLEMENTED |
| codexVersionValidated | 0.144.3 |
| codexAppServerValidation | PASS: stable schema, stdio handshake, sanitized account/model reads |
| pullRequest | OJ3-B-H draft PR #4 — hardening functional commit `523ebb18a805c2dad1cf03fb7649ae27ebbd02f1`; live head/checks must be confirmed on GitHub |
| lifecycleAutomation | DISABLED |
| ci | OJ3-B-H current CI: not yet available; historical run `29603505953` is not reusable; compileall and manual fake app-server harness PASS; local pytest unavailable |
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

Evidence (2026-07-17 16:03:42 -03:00): OJ3-B-H functional commit
`523ebb18a805c2dad1cf03fb7649ae27ebbd02f1` hardens per-generation lifecycle
isolation, fatal protocol shutdown, safe server-response serialization and
concurrent close. PR #4 remains draft; its current live head and checks must be
confirmed on GitHub after push. No current CI result is claimed here.

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
remain unauthorized. OJ3-B-H is limited to the transport/client-core draft PR
and stops after its current CI gate.

OJ2/OJ2-V report: `docs/project/research/OJ2-CODEX-RUNTIME-AUDIT.md` (CANONICAL).

Human architectural review: approved on 2026-07-17. OJ2 is approved with GO
only for PR A — External Agent Contract. OJ3-A is merged; OJ3-B-H is draft and
stopped pending the current CI gate;
threads, reconnection, concurrency, final sandbox, telemetry and end-to-end
integration remain unproven; OJ3-B does not implement CodexAgent.
