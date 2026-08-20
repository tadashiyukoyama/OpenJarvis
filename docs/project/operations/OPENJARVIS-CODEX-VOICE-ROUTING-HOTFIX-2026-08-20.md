# OpenJarvis Codex voice-routing hotfix — 2026-08-20

Status: PRODUCTION DEPLOYED AND AUDITED
Owner: Cesar Yukoyama / Codex
Branch: `codex/edge-live-relay-release`
Functional SHA: `b129eaf591675fa411e2ae164211952ac96c67d7`
Functional tree: `eb44c6419957a699a871ad21c7a060f4739fe3d9`
Publication target: private `cesaryukoyama28-eng/openjarvis-codex`, branch `main`

## Incident

The operator asked Jarvis by voice to send a controlled test command to Codex.
Gemini selected the correct canonical tool, but no approval appeared and Jarvis
reported that the command could not be sent.

Production evidence established the exact failure boundary:

- session: `jas_97e7c02679dc475fa790efa99ce66da4`;
- event sequences: `22002` and `22004`;
- event type: `tool_call_rejected`;
- public code: `TOOL_INTENT_MISMATCH`;
- Gemini function: `codex_delegate_task`;
- resolved tool: `codex.delegate`;
- no action, approval or job was created by either rejected attempt.

The committed transcript contained an explicit hand-off, a named command and a
canonical Codex mention. Speech recognition had rendered the first destination
as “Cortex”, and the later phrase also contained the word “funcionando”. The
new backend classifier required the hand-off verb and destination to match a
bounded positional expression. When that expression missed, `funcionando`
caused the same turn to be classified as `codex.status`; the deterministic guard
then rejected Gemini's correct `codex.delegate` selection.

This incident is separate from the prior trusted-payload validation defect fixed
by SHA `3d311bcba5a6ce3629458ab0a8b8515a06913d71`.

## Old Jarvis comparison

The known functional reference at commit `3f21c5b` classified Codex routing from
an explicit action and the Codex destination anywhere in the consolidated turn.
It did not impose a maximum distance between the action and destination.

The restored server-side rule preserves that behavior without regressing the
new read-only status and history tools:

- a common ASR alias, `Cortex`, is recognized only as a Codex destination;
- an explicit hand-off plus a named work item (`command`, `task` or `request`)
  remains delegation anywhere in the committed turn;
- direct Codex task forms continue to use the existing deterministic rules;
- pure status phrases such as “is Codex working?” remain `codex.status`;
- every delegation still requires the existing visual approval;
- a continuation such as “again” alone does not silently authorize a mutation.

No second orchestrator, generic command endpoint or model-only authorization was
introduced. Gemini proposes the canonical tool, the Core validates the committed
voice intent, and the visual decision remains the sole mutation authority.

## Source scope

Only two functional files changed:

- `src/openjarvis/server/jarvis_agent/services/intent_routing.py`;
- `tests/server/jarvis_agent/test_intent_routing.py`.

The production module remains small and the change adds no migration, table,
endpoint, credential, provider mutation or frontend authority.

## Validation

| Gate | Result |
|---|---|
| Exact production transcript through proposal boundary | `approval_required`; no adapter execution |
| Focused intent suite | 16 passed |
| Agent Core suite | 210 passed; 5 upstream deprecation warnings |
| Agent Core + Edge + MCP + Codex matrix | 384 passed + 4 subtests; 45 upstream deprecation warnings |
| Frontend Vitest | 112 passed in 29 files |
| TypeScript and Vite/PWA build | passed |
| Ruff check and format | passed |
| Python compileall | passed |
| Patch whitespace | `git diff --check` passed |
| Publication scanner | PASS; 2,445 tracked files; no forbidden path or detected secret |
| Source archive | 2,756 entries; zero forbidden/private entries |
| Image-level regression | PASS with networking disabled and read-only filesystem |

Preserved operator files were not committed or archived:
`.manus-audit/`, `frontend/pnpm-lock.yaml` and `node_modules/`.

## Artifact and rollback identity

| Item | Value |
|---|---|
| Source archive | `/opt/openjarvis/backups/source-b129eaf591675fa411e2ae164211952ac96c67d7.tar.gz` |
| Archive bytes | `43189609` |
| Archive SHA-256 | `e17ec7132ad0f904f29708e6636e29eab834e0c65a27a6581715628f459b7940` |
| Production image | `openjarvis-core:b129eaf591675fa411e2ae164211952ac96c67d7` |
| Image ID | `sha256:245746b6647aae096e78bce1954e5b926ee2318f1f2d648c0884d2ce4261fd04` |
| Image size | `177980206` bytes |
| Rollback image | `openjarvis-core:3d311bcba5a6ce3629458ab0a8b8515a06913d71` |
| Deployed at | `2026-08-20T21:32:58Z` |

Validated pre-deploy backups:

- `/opt/openjarvis/backups/jarvis-agent-20260820T212742Z-3d311bcba5a6ce3629458ab0a8b8515a06913d71.sqlite3`
  — SHA-256 `07c390d2c620bf6ea973fc22544e4551e683d047b2221697ff89e4828eb8358f`;
- `/opt/openjarvis/backups/operational-events-20260820T212742Z-3d311bcba5a6ce3629458ab0a8b8515a06913d71.sqlite3`
  — SHA-256 `c9bbaa157c0de25857e99ae84be90088645c9502bfbe85b83bea2a835d2a24e3`;
- Compose SHA-256
  `1c91bbbc492c3a99d3374a76ca757231143a6683c62d07a669bdaea0a2575b51`;
- private environment SHA-256
  `e0d9bc52e1f395291648fc47e4ae6bea135745d1235a0f505a397de774cc6838`;
- previous release manifest SHA-256
  `a9dbc5acc8d95ca1e4e206f68c3b457361b1370b82e5c1f29727c9b54aeada82`.

Both SQLite backups returned `quick_check=ok`. The copies in the state volume
and `/opt/openjarvis/backups` had identical hashes. No credential value appears
in this report.

## Controlled deployment evidence

The first activation was automatically rolled back because the audit script,
not the application, contained two invalid assumptions: it checked catalog
availability before waiting for Edge reconnection and looked for `tool_id`
instead of the canonical public field `id`. The rollback restored `3d311bc...`,
health, Edge and the unchanged database counts before any retry.

The corrected activation passed:

- active image and image ID matched the functional SHA;
- container health was `healthy`, restart count was `0`;
- public TLS health returned HTTP 200;
- the Edge device was `ONLINE` after reconnection;
- 24 of 24 catalog tools were available and `codex.delegate` was present;
- both live databases returned `quick_check=ok`;
- action, approval and job counts remained `37 | 2 | 1` before and after;
- the post-deploy error-log gate returned zero matches;
- local Codex app-server listened on `127.0.0.1:8131`;
- the local Edge Worker remained running and connected outbound to production.

No proposal endpoint was called during deployment smoke. No Codex turn,
WhatsApp message, e-mail, provider reaction, read marker or other external
mutation was executed.

## Rollback

If the operator acceptance test exposes a regression:

1. preserve the action, approval, job and event evidence;
2. set `OPENJARVIS_IMAGE_TAG` to
   `3d311bcba5a6ce3629458ab0a8b8515a06913d71`;
3. recreate only the `core` service from `/opt/openjarvis/compose.yaml`;
4. require container health, public TLS health, Edge `ONLINE` and 24/24 tools;
5. retain the additive databases unless an independently verified database
   fault requires restoring the validated backups.

No destructive migration, DNS/OpenResty change, credential rotation, GitHub
Action, real Codex command or provider mutation was part of this release.
