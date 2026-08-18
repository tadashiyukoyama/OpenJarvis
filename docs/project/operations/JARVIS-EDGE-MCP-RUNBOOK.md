# Jarvis Edge Worker and MCP release runbook

Status: CANONICAL — INSTALLATION NOT YET AUTHORIZED
Owner: Cesar Yukoyama / Codex
Last verified: 2026-08-18 13:20:52 -03:00
Implementation base: `4b2b16ab6ffce6f100180cfa40780f8296690515`
Branch: `codex/vps-edge-mcp`

## Safety boundary

This runbook prepares a controlled release; it is not permission to access the
VPS, change DNS/TLS/OpenResty, run AceleraChat migrations, create credentials,
push GitHub, install a Windows task or send a real message/e-mail. Obtain an
explicit release authorization before any external or service-changing step.

Never print private values. The private handoff remains outside Git at the path
supplied by Cesar. Operators may verify required variable names and presence,
but reports contain only fingerprints, IDs already classified as non-secret and
redacted paths.

## Release inputs

Required repositories and contracts:

- OpenJarvis: `D:\dev\workspaces\openjarvis`;
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
Set-Location -LiteralPath D:\dev\workspaces\openjarvis
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
$python = '.\.venv\Scripts\python.exe'
$ruff = '.\.venv\Scripts\ruff.exe'
$env:PYTHONPATH = 'src'

& $python -m pytest tests/server/jarvis_agent tests/edge_worker tests/mcp -q
& $ruff check src/openjarvis/server/jarvis_agent src/openjarvis/edge_worker `
  src/openjarvis/mcp tests/server/jarvis_agent tests/edge_worker tests/mcp
& $ruff format --check src/openjarvis/server/jarvis_agent `
  src/openjarvis/edge_worker src/openjarvis/mcp tests/server/jarvis_agent `
  tests/edge_worker tests/mcp
& $python scripts/workspace/export-jarvis-agent-contracts.py --check

Push-Location frontend
npm test -- --run
npm exec tsc -- --noEmit
npm run build
Pop-Location
```

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

## Gate 3 — Windows Edge Worker installation

This gate requires separate authorization because it registers a persistent
Scheduled Task.

Preconditions:

- Codex app-server is reachable only at `127.0.0.1:8131`;
- project roots are the intended D: workspaces;
- private env file is readable only by Cesar's Windows account;
- WSS hostname has valid TLS;
- no existing task/process owns the same device ID or pipe.

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

## Gate 4 — Codex MCP configuration

Copy the example block from
`deploy/windows/codex-agent-mcp.example.toml` into the intended Codex project
configuration only after authorization. It contains no secret; the wrapper
loads `agent-mcp.env` from D: and starts only the MCP STDIO facade.

Verify through an MCP protocol client:

- `initialize` returns safety instructions;
- `tools/list` returns at most 13 available tools;
- no `codex.*` or `codex_delegate_task` exists;
- an unavailable provider removes its tools;
- read calls pass through the Agent Core;
- mutation creates a visual proposal and waits;
- closing STDIO leaves the Edge Worker running;
- logs never enter stdout.

Do not configure remote `/mcp`; it is outside this release.

## Gate 5 — VPS container preparation

This gate is descriptive until VPS access is explicitly authorized.

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
9. SSE/poll reconciliation and ephemeral Gemini token pass.
10. Codex status/history read jobs complete.

Required failure smokes:

- wrong/missing browser, Edge, relay and webhook credentials;
- worker offline before approval returns `DEVICE_OFFLINE` without a queue;
- WSS disconnect/reconnect resumes only accepted work;
- duplicate frame/job/action executes once;
- device revocation disconnects and prevents re-registration;
- nested approval accepts/denies only the displayed hash;
- stale session callback is ignored;
- Core and worker restart reconcile without repeating mutation;
- no endpoint reaches public 8131.

No message, reaction, campaign, broadcast or e-mail may be sent in this gate.
A first mutation requires a separate authorization naming channel, inbox,
controlled recipient, exact content, time and observer.

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

Current source rollback point is the local AceleraChat checkpoint
`4b2b16ab6ffce6f100180cfa40780f8296690515`. The earlier observed base is
`ec5e22e360943eb77560be3b9e5ea8ab7300b5eb`.

## Troubleshooting matrix

| Symptom | Verify first | Safe response |
|---|---|---|
| Edge shown offline | WSS TLS, device ID, heartbeat and revocation | fix identity/network; create a new proposal afterward |
| MCP unavailable | scheduled task, named pipe and local token ACL | restart worker only after identifying cause |
| MCP tools missing | provider capabilities and canonical catalog | do not add a manual MCP tool |
| Core relay 401 | independent relay-token fingerprints | rotate/configure outside logs |
| Codex busy | selected task state | fail fast; no hidden queue |
| approval never appears | action/job correlation and SSE/poll cursor | do not approve through voice or API shortcut |
| accepted job has no final result | Edge spool, attempt, lease and history | reconcile; never retry uncertain mutation |
| PWA health fails | authenticated `/health`, CSP and generated Workbox asset | test exact gateway routes |
| webhook gap | per-resource sequence and read-only backfill | reconcile without provider mutation |

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
