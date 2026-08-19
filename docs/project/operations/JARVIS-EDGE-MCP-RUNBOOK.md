# Jarvis Edge Worker and MCP release runbook

Status: CANONICAL — CONTROLLED RELEASE ACTIVE; MUTATIONS DISABLED
Owner: Cesar Yukoyama / Codex
Last verified: 2026-08-19
Applies to code SHA: `1ecb90ac6191c27501c2ca497c2deecdf5bad8e0`
Production-source baseline: `9874381c9df924e9d439ecb958761a6df27586b1`
Branch: `codex/edge-live-relay-release`
Supersedes: none
Superseded by: none

## Safety boundary

This runbook prepares and governs the controlled release authorized by Cesar on
2026-08-19. The authorization covers the initial private fast-forward release,
one gate-driven local MCP hotfix publication, validated backup/build/deploy,
rollback and read-only smoke. It does not cover new DNS changes, AceleraChat
migrations, a real Codex turn, channel mutations or a real WhatsApp/e-mail send;
those remain separate explicit gates.

Never print private values. The private handoff remains outside Git at the path
supplied by Cesar. Operators may verify required variable names and presence,
but reports contain only fingerprints, IDs already classified as non-secret and
redacted paths.

## Release inputs

Required repositories and contracts:

- current release worktree: `D:\dev\workspaces\openjarvis-edge-release`;
- reusable local Python environment: `D:\dev\workspaces\openjarvis\.venv`;
- AceleraChat release contract: `2026-08-18.2`;
- Edge schemas: `contracts/edge/v1`;
- Agent OpenAPI: `contracts/jarvis-agent.openapi.json`;
- Core container: `deploy/vps/Dockerfile` and `compose.yaml`;
- OpenResty sample: `deploy/vps/openresty-openjarvis.conf.example`;
- Edge Windows scripts: `scripts/edge`;
- private files: only under `D:\dev\runtime\openjarvis\private` on Windows
  and `/opt/openjarvis/private` on the VPS.

The release report must record a clean final OpenJarvis SHA and immutable image
digest. Never deploy from a working tree, archive or copied `node_modules`.

## Gate 0 — local source and secret preflight

Run read-only checks:

```powershell
Set-Location -LiteralPath D:\dev\workspaces\openjarvis-edge-release
git status --short --branch
git rev-parse HEAD
git worktree list --porcelain
git diff --check
```

Confirm:

- expected branch and final SHA;
- no unknown tracked change;
- `.manus-audit/`, root `node_modules/` and `frontend/pnpm-lock.yaml` are not
  part of the release;
- `.private`, runtime databases, logs, QR values and key files are ignored;
- no secret appears in staged diff or generated contracts;
- no second worktree or process is mistaken for the release source.

Stop if any item cannot be classified. Do not run `git clean` or delete it.

## Gate 1 — deterministic local validation

Use the existing locked environments; do not install a missing dependency just
to make the gate green without approval.

```powershell
$sourceRoot = 'D:\dev\workspaces\openjarvis-edge-release'
$python = 'D:\dev\workspaces\openjarvis\.venv\Scripts\python.exe'
$env:PYTHONPATH = Join-Path $sourceRoot 'src'
Set-Location -LiteralPath $sourceRoot

$testTargets = @(
  'tests/server/jarvis_agent',
  'tests/edge_worker',
  'tests/mcp',
  'tests/server/test_codex_turn_dispatch.py',
  'tests/server/test_codex_sync_events.py',
  'tests/server/test_codex_history_reader.py',
  'tests/server/test_codex_catalog.py',
  'tests/server/test_channel_authority.py',
  'tests/server/test_spa_fallback.py',
  'tests/server/test_connectors_router.py',
  'tests/server/test_jarvis_sources_router.py',
  'tests/integrations/test_codex_conversation.py',
  'tests/integrations/test_codex_app_server_websocket.py',
  'tests/integrations/test_codex_app_server.py',
  'tests/agents/test_codex_agent.py'
)
& $python -m pytest -q @testTargets
& $python -m ruff check src/openjarvis/server src/openjarvis/edge_worker `
  src/openjarvis/integrations/codex_protocol.py src/openjarvis/mcp `
  tests/server tests/edge_worker tests/integrations/test_codex_conversation.py `
  tests/integrations/test_codex_app_server_websocket.py `
  tests/integrations/test_codex_app_server.py tests/mcp `
  tests/agents/test_codex_agent.py
& $python -m ruff format --check src/openjarvis/server `
  src/openjarvis/edge_worker src/openjarvis/integrations/codex_protocol.py `
  src/openjarvis/mcp tests/server tests/edge_worker tests/mcp
& $python scripts/workspace/export-jarvis-agent-contracts.py --check

Push-Location frontend
npm test -- --run
npm exec tsc -- --noEmit
npm run build
Pop-Location
```

Current local evidence for integrated code SHA `1ecb90a`: 538 directed Python
tests plus 4 subtests, 52 isolated Edge Worker tests and 106 frontend tests in
27 files passed.
TypeScript, Vite/PWA, Ruff check/format, generated contracts, `compileall`, ten
Edge PowerShell parses, Compose YAML, MCP TOML and `git diff --check` also
passed. These are local gates only. The container, OpenResty and WSS gates were
later completed under controlled release; the same-task turn and final visual
smokes remain separate gates.

The repository-wide upstream suite is a diagnostic, not this release gate: it
contains unrelated optional-provider and external-integration tests. If it is
run, compare every failure against the correction baseline before changing code.
On 2026-08-19 its first failure was the unchanged
`test_security_without_engine_keeps_capability_and_audit`; no file involved in
that failure differs between the baseline and this branch.

Also parse every `scripts/edge/*.ps1` and `.psm1` with the PowerShell AST parser.
When Docker is available, render `docker compose config`, build by full SHA and
record the resulting digest. A static artifact test is evidence only; it does
not replace a real container build.

## Gate 2 — private configuration preparation

Create independent random credentials outside Git. Never reuse a value between:

1. OpenJarvis to AceleraChat Bearer;
2. AceleraChat webhook HMAC;
3. Edge WSS device Bearer;
4. Edge-to-Core MCP relay Bearer;
5. local MCP named-pipe token;
6. browser Basic Auth;
7. Gemini server keys.

Edge WSS, Edge-to-Core relay and local named-pipe tokens must be generated with
at least 32 high-entropy characters. A previous Edge credential is accepted
only with the same minimum strength and an explicit timezone-aware expiry.

Copy templates without values in source:

```powershell
Copy-Item deploy\windows\edge-worker.env.example `
  D:\dev\runtime\openjarvis\private\edge-worker.env
Copy-Item deploy\windows\agent-mcp.env.example `
  D:\dev\runtime\openjarvis\private\agent-mcp.env
```

On the VPS, copy `deploy/vps/core.env.example` to
`/opt/openjarvis/private/core.env`, mode `0600`, owned by the service operator.
The Windows Edge Core-relay token must match the VPS
`OPENJARVIS_MCP_AUTH_TOKEN`; Codex receives neither value. The local pipe token
appears only in the two private Windows files.

Before release, confirm selected inbox IDs from the AceleraChat API. Never infer
them by display name.

Keep the bounded replay controls explicit in the private Edge configuration:

- `OPENJARVIS_EDGE_SPOOL_MAX_FRAMES=10000`;
- `OPENJARVIS_EDGE_SPOOL_MAX_BYTES=67108864`;
- `OPENJARVIS_EDGE_REPLAY_BATCH_SIZE=100`.

Changing them requires a measured capacity review; removing a limit is not an
accepted troubleshooting step.

These variables bound the normal event partition. Code SHA `df82a3c` retains a
reserve of exactly 64 terminal frames, each limited by the 256 KiB Edge protocol
maximum. This fixed 16 MiB reserve is not a second general-purpose spool and is
not runtime-configurable. Do not reduce or reuse it without proving that the
maximum of 64 simultaneously reported active jobs can still persist a terminal
outcome each.

Admission is valid only when the worker job row and its `job.accepted` frame
commit together. A full normal partition must produce no local job and no
executor call. A valid accepted job owns terminal capacity; an invalid,
non-serializable or oversized terminal result must become the small durable
`UNKNOWN` outcome. Never enlarge the frame limit, truncate an arbitrary
mutation silently or retry it to make this gate pass.

An omitted `data` or `references` result field normalizes to an empty mapping.
When present, each field must be a mapping; a list, scalar or null value must
produce the small durable `UNKNOWN / EXTERNAL_RESULT_UNKNOWN` outcome.

## Gate 3 — Windows Edge Worker installation

This gate requires separate authorization because it registers a persistent
Scheduled Task.

Preconditions:

- Codex app-server is reachable only at `127.0.0.1:8131`;
- project roots are the intended D: workspaces;
- private env file is readable only by Cesar's Windows account;
- WSS hostname has valid TLS;
- no existing task/process owns the same device ID or pipe.

Before the first Worker start at SHA `df82a3c`, stop the Worker if it exists,
copy its local SQLite spool to the dated backup directory and run
`PRAGMA integrity_check` against the copy. Startup adds the nullable
`terminal_job_id` marker and its partial unique index idempotently, then runs an
integrity check. This is a local additive schema migration; it does not touch
the VPS or AceleraChat databases. Never delete the backup during rollout.

Validate scripts without installing:

```powershell
pwsh -NoProfile -File scripts\edge\Manage-OpenJarvisEdgeTask.ps1 -Action Status
```

Install and start only after authorization:

```powershell
pwsh -NoProfile -File scripts\edge\Manage-OpenJarvisEdgeTask.ps1 -Action Install
pwsh -NoProfile -File scripts\edge\Manage-OpenJarvisEdgeTask.ps1 -Action Start
```

The task runs as the current interactive user with limited privileges, ignores
duplicate instances and restarts after failure. Logs rotate at 10 MiB with five
backups by default under `D:\dev\runtime\openjarvis\logs`.

Acceptance:

- one outbound WSS connection;
- register and each periodic heartbeat acknowledged; job lifecycle frames are
  covered by the next heartbeat acknowledgement and do not receive individual
  `edge.heartbeat_ack` frames;
- capability snapshot truthful;
- named pipe bound once;
- 8131 remains loopback;
- stopping Codex/MCP does not stop the worker;
- worker offline appears offline at the Core.

Internal Codex transport capabilities advertised by the Worker are
`codex.status`, `codex.history`, `codex.catalog`, `codex.subscribe`,
`codex.desktop_refresh` and `codex.delegate`. The subscription and Desktop
refresh capabilities are transport plumbing and are not added to the public
MCP catalog. `codex.subscribe` must complete before the Core marks a selected
conversation live.

## Gate 4 — Codex MCP configuration

Copy the example block from
`deploy/windows/codex-agent-mcp.example.toml` into the intended Codex project
configuration only after authorization. It contains no secret; the wrapper
loads `agent-mcp.env` from D: and starts only the MCP STDIO facade.

On Windows, use the absolute command
`C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe` with
`-NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass`. Do not assume
`pwsh.exe` is present in the clean Desktop PATH. Save and restart Codex after
changing MCP configuration.

Verify through an MCP protocol client:

- `initialize` returns safety instructions;
- `tools/list` returns at most 13 available tools;
- no `codex.*` or `codex_delegate_task` exists;
- every live `READ` tool has `readOnlyHint=true`, `destructiveHint=false` and
  `idempotentHint=true`; an unknown effect fails the catalog closed;
- an unavailable provider removes its tools;
- read calls pass through the Agent Core;
- mutation creates a visual proposal and waits;
- closing STDIO leaves the Edge Worker running;
- logs never enter stdout.

Do not configure remote `/mcp`; it is outside this release.

## Gate 5 — VPS container preparation

This gate was completed for the active Core release. Re-run every item for any
future image; the exact current digest and rollback evidence are recorded in
`OPENJARVIS-CONTROLLED-RELEASE-2026-08-19.md`.

1. Record VPS resource, container, port and OpenResty preflight.
2. Confirm no conflict on loopback port 8180 and no second 80/443 listener.
3. Create `/opt/openjarvis` independently from AceleraChat directories.
4. Build/tag the image with the full clean OpenJarvis SHA.
5. Record image digest and scanner result.
6. Keep `OPENJARVIS_EXTERNAL_MUTATIONS_ENABLED=false`.
7. Start `deploy/vps/compose.yaml` with one Core replica.
8. Verify container user 10001, read-only root, limits, volume and health.
9. Do not mount Docker socket, SSH keys, AceleraChat filesystem or host source.

The Compose service binds only `127.0.0.1:8180`. OpenResty is the public TLS
boundary. A Docker build is mandatory before claiming the artifact reproducible.

## Gate 6 — OpenResty, DNS and TLS

Extend the existing OpenResty configuration with an isolated virtual host;
never start a competing proxy. Replace placeholders only in private deployment
configuration.

Required behavior:

- HTTP redirects to HTTPS;
- `/healthz` is minimal;
- `/jarvis`, assets, `/health`, Agent and Gemini APIs require interface auth;
- `/edge` preserves WebSocket upgrade and long timeout;
- the exact AceleraChat webhook bypasses Basic Auth but still requires backend
  HMAC, timestamp, event ID, body schema and 1 MiB limit;
- `/local-agent` is Edge-only and uses an independent Bearer;
- `/mcp` remains absent;
- all other paths return 404;
- no query, Authorization or HMAC value enters logs.

Run `openresty -t` or the platform equivalent before reload. A valid DNS A
record and TLS certificate are prerequisites; their creation is an external
change requiring authorization.

## Gate 7 — startup order and read-only smoke

Activation order:

1. Core starts with external mutations disabled.
2. Internal and public `healthz` pass.
3. OpenResty authentication and deny-by-default pass.
4. Signed webhook fixture passes; no channel operation is emitted.
5. AceleraChat health/catalog/inboxes pass read-only.
6. Edge Worker connects and advertises Codex capabilities.
7. MCP initializes and lists filtered tools.
8. PWA opens on desktop and tablet.
9. SSE event relay, history reconciliation and ephemeral Gemini token pass.
10. Codex status/history/subscribe read jobs complete.
11. A sanitized `codex.event` fixture crosses Worker -> WSS -> Core exactly
    once, including after replay of the same `event_id`.
12. Desktop refresh is routed to `codex.desktop_refresh` on Windows; the VPS
    does not dispatch `codex://` itself. The authenticated gateway strips a
    browser-supplied action header and injects the trusted loopback header.
13. Closing the isolated tracked Desktop sentinel releases the exact listener
    even when another private Desktop exists; PID/path mismatch stops nothing.
14. Unknown `/v1/*` paths return JSON `404`, never the frontend `index.html`.
15. Direct Gmail/IMAP and WhatsApp/Baileys source routes are absent in VPS mode,
    blocked connector IDs are omitted from discovery and direct access returns
    `404`.

Required failure smokes:

- wrong/missing browser, Edge, relay and webhook credentials;
- worker offline before approval returns `DEVICE_OFFLINE` without a queue;
- WSS disconnect/reconnect resumes only accepted work;
- duplicate frame/job/action executes once;
- device revocation disconnects and prevents re-registration;
- nested approval accepts/denies only the displayed hash;
- stale session callback is ignored;
- Core and worker restart reconcile without repeating mutation;
- fill the normal spool partition, complete both a successful and failing local
  job, and prove neither remains `RUNNING` and each has one replayable terminal
  frame;
- exhaust the terminal reservation and prove the next offer is rejected before
  execution, then acknowledge one terminal frame and prove admission resumes;
- no endpoint reaches public 8131.

No message, reaction, campaign, broadcast or e-mail may be sent in this gate.
A first mutation requires a separate authorization naming channel, inbox,
controlled recipient, exact content, time and observer.

The same-task Codex acceptance turn is also a separate authorization. For that
test, call only `POST /v1/codex/threads/{thread_id}/turns` with the selected
immutable task, project root, client message ID and conversation ID. Capture in
order: `agent_turn_start`, `turn_started`, at least one public delta or completed
assistant message, item/status events when present, `turn_completed`, canonical
history reconciliation and the final Desktop remount. Confirm that a duplicate
Edge frame does not duplicate text and that no hidden second turn remains
active.

## Rotation and revocation

Device rotation:

1. create a new random value outside Git;
2. configure it as Core current and move old current to previous;
3. set an explicit previous expiry, target 24 hours;
4. update the private worker file;
5. restart only the worker;
6. verify current credential fingerprint and connection;
7. remove previous after overlap.

For suspected compromise, revoke the device immediately through the protected
operator endpoint using a visual decision channel, stop the Windows task and
replace both Edge and relay credentials. Do not clear revoked state by editing
SQLite. Preserve the ledger for investigation.

## Rollback

Before release, record the active image/digest and a verified backup of the
OpenJarvis volume. Rollback does not delete state.

1. Disable new external mutations/offers.
2. Inspect or cancel non-terminal jobs; never assume timeout means failure.
3. Stop the Windows Edge task.
4. Disable the AceleraChat integration/webhook if it was activated.
5. restore the prior OpenJarvis image/Compose and OpenResty virtual-host config;
6. preserve Edge/Core ledgers and logs;
7. verify AceleraChat remains healthy without OpenJarvis;
8. restore the Windows source to the recorded prior SHA only after preserving
   the current patch/evidence.

The source rollback point is the private production-source baseline
`9874381c9df924e9d439ecb958761a6df27586b1`. The runtime preflight observed
`openjarvis-core:3586569fe597943baa990dfb18fa5f7a7d2c9b69` as the active prior
image; re-confirm its immutable image ID immediately before cutover. Preserve
evidence first, then revert integrated checkpoints in reverse order when a
narrower source rollback is proven safe: `1ecb90a`, `df82a3c`, `c31bd49`, `955cf84`,
`49e99f2`, `4a1db68`, `35ee771`, `21c9481`, `5493484`, `343a62c`, `95f3d14`,
`84bcba7`. Do not mix a source rollback with deletion of Edge/Core ledgers.

## Troubleshooting matrix

| Symptom | Verify first | Safe response |
|---|---|---|
| Edge shown offline | WSS TLS, device ID, heartbeat and revocation | fix identity/network; create a new proposal afterward |
| MCP unavailable | scheduled task, named pipe and local token ACL | restart worker only after identifying cause |
| MCP absent only in Codex Desktop | absolute Windows PowerShell command, `config.toml`, Desktop restart | fix the command first; do not add a second MCP server |
| MCP tools missing | provider capabilities and canonical catalog | do not add a manual MCP tool |
| Core relay 401 | independent relay-token fingerprints | rotate/configure outside logs |
| Codex busy | selected task state | fail fast; no hidden queue |
| `active writer` while Desktop appears idle | inspect the opt-in topology, exact runtime owner and private Desktop child | follow `JARVIS-SHARED-CODEX-RUNTIME.md`; never persist a redirect or create another thread |
| approval never appears | action/job correlation and SSE/poll cursor | do not approve through voice or API shortcut |
| accepted job has no final result | normal spool, terminal reserve, `terminal_event_id`, attempt, lease and history | keep the ledger; reconcile or replay, never retry uncertain mutation |
| PWA health fails | authenticated `/health`, CSP and generated Workbox asset | test exact gateway routes |
| webhook gap | per-resource sequence and read-only backfill | reconcile without provider mutation |
| unknown API returns the PWA | backend namespace guard and deployed SHA | stop the release; an unknown `/v1/*` must be JSON `404` |
| direct Gmail/WhatsApp appears on VPS | `OPENJARVIS_CORE_MODE`, connector discovery and route inventory | stop the release; AceleraChat must remain the sole authority |

## Evidence and completion report

Record:

- date/time, operator, branch, source SHA and image digest;
- prior image/digest and backup checksum;
- DNS/TLS/OpenResty changes;
- container identity, health, limits and exposed ports;
- device and credential fingerprints only;
- authorized inbox IDs without tokens;
- automated tests and every smoke result;
- visual desktop/tablet evidence path;
- external mutation count, expected to be zero;
- deploy, migration, credential and GitHub declarations;
- rollback decision and remaining blockers.

Do not declare production readiness until the working tree is clean, the image
build is reproducible, the VPS and Windows services are installed under an
authorized change window, and the read-only plus visual gates pass.
