# OpenJarvis deterministic delegation and history release — 2026-08-20

Status: CANONICAL EVIDENCE
Owner: Cesar Yukoyama / Codex
Functional SHA: `846127cfa76680d11dd686ea052f5b7fdc7c4818`
Functional tree: `f250910f748f29f119a8bf4c72525015af57eb16`
Branch: `codex/edge-live-relay-release`
Publication target: private `https://github.com/cesaryukoyama28-eng/openjarvis-codex`, branch `main`

## 1. Release objective

Restore the professional operational behavior expected from the earlier Jarvis:
explicit Codex commands must reach the correct typed tool, stop for visible
approval, remain idempotent and appear in persistent history. AceleraChat must
remain the sole VPS authority for e-mail and WhatsApp.

This release does not restore direct Gmail/IMAP or Baileys execution and does
not authorize an unapproved Codex/provider mutation.

## 2. Implemented behavior

- `intent_routing.py` deterministically maps explicit contact/command/ask-Codex
  phrases to `codex.delegate`.
- A conflicting Gemini proposal fails as `TOOL_INTENT_MISMATCH` before an
  action, approval or job is created.
- Exact proposal retries resolve the original action even after final-turn text
  redaction; no second execution is possible.
- Function responses identify the requested tool, confirmed operation state and
  claim boundary, preventing false narration of a status read as delegation.
- `GET /v1/jarvis/agent/events/history` exposes bounded durable history scoped by
  normalized project and selected Codex task.
- `operational-events.sqlite3` persists privacy-safe operational events.
- The Jarvis panel merges durable and live history and displays the real
  executable catalog, `codex.delegate` availability and blocked reasons.
- Production Compose no longer overrides the private mutation feature gate with
  a source-hardcoded false value. Policy and visual approval remain authoritative.

## 3. Source and artifact identity

| Item | Value |
|---|---|
| Functional commit | `846127cfa76680d11dd686ea052f5b7fdc7c4818` |
| Functional tree | `f250910f748f29f119a8bf4c72525015af57eb16` |
| Source archive | `/opt/openjarvis/backups/source-846127cfa76680d11dd686ea052f5b7fdc7c4818.tar.gz` |
| Archive bytes | `43161408` |
| Archive SHA-256 | `06f548bc86d63874fb8575f16c4dcfe47cf99985b51507a5ff7fa9a84594351f` |
| Archive audit | 2,737 entries; forbidden/private paths absent |
| New image | `openjarvis-core:846127cfa76680d11dd686ea052f5b7fdc7c4818` |
| New image ID | `sha256:8ba92fb7d8ddeffe2f05cbc9640981bce5d22a7f42d829014bc89f2cfc8c7a50` |
| Previous image | `openjarvis-core:2ed693755e1cf0a21a0cb7cb704fbdd3c4294415` |
| Previous image ID | `sha256:146c1cf9c5bfa991e8c4f0b5113d4bde286a8f3b3b0c5138c2ce020e466c8664` |

The image was built on the production VPS from the verified archive. No GitHub
Action was used for the build or deployment.

## 4. Automated gates

| Gate | Result |
|---|---|
| Agent Core + Gemini directed matrix | 173 passed; 37 upstream deprecation warnings |
| Frontend Vitest | 112 passed in 29 files |
| TypeScript | no-emit check passed |
| Vite/PWA | production build passed; existing chunk/import warnings only |
| Ruff | check passed; 842 Python files format-compliant |
| PowerShell | 25 scripts parsed without error |
| OpenAPI | regenerated; reference/release tests passed |
| Patch quality | `git diff --check` passed |
| Secret/publication pre-gate | staged secret scan and source-archive audit passed |

## 5. Production preflight and backup

Before replacement, production health was good, one Edge device was connected
and the active image was recorded. The existing Jarvis Agent database returned
`PRAGMA quick_check=ok`.

Backups retained on the VPS:

| Item | Path or digest |
|---|---|
| Jarvis Agent database | `/opt/openjarvis/backups/jarvis-agent-20260820T192324Z-2ed693755e1cf0a21a0cb7cb704fbdd3c4294415.sqlite3` |
| Database SHA-256 | `ab6fd9f924a04947e75f14bd1ad8361fcdd82aab8610ca23d133c2e02820c6a6` |
| Compose | `/opt/openjarvis/backups/compose-20260820T192324Z-2ed693755e1cf0a21a0cb7cb704fbdd3c4294415.yaml` |
| Private environment | `/opt/openjarvis/backups/core.env-20260820T192324Z-2ed693755e1cf0a21a0cb7cb704fbdd3c4294415` |
| Pre-inbox-correction environment | `/opt/openjarvis/backups/core.env-before-whatsapp-20260820T192904Z` |
| Release identity | `/opt/openjarvis/release-manifest.json` and `/opt/openjarvis/active-image` |

No credential value is present in this report.

## 6. Deployment and production proof

- Isolated image smoke passed with networking disabled: health, 16 tools and
  the durable history route were present.
- Controlled replacement used an automatic rollback trap until health and image
  identity passed.
- Public `https://openjarvis.meugerenciador.pro/healthz` returned HTTP 200 and
  TLS verification returned zero.
- The production container used the expected image, had zero restarts and no
  error-level log entry in the final 15-minute audit.
- Both the Jarvis Agent database and new operational-event database returned
  `quick_check=ok`.
- One Edge device was connected. All 16 catalog tools were available and no
  tool was blocked.
- The stale WhatsApp selector ID 19 was corrected to the active connected
  Evolution inbox ID 20 (`AiFoodmanager`). E-mail inbox ID 16 remained valid.
- The private external-mutation gate is enabled. Exact visual approval is still
  mandatory for each mutation/delegation.
- The temporary remote build directory was removed after validating the active
  image. The source archive, release manifest and rollback backups remain.

## 7. Safe production smoke

The smoke used a synthetic session and did not approve execution:

1. explicit Codex delegation intent paired with `codex_get_status` returned
   `TOOL_INTENT_MISMATCH`;
2. the correct `codex_delegate_task` proposal returned `approval_required`;
3. an exact retry returned the same action; action count remained one;
4. the visual decision was denial;
5. no Edge job was created;
6. durable history contained session, committed turn, rejected tool, approval
   request, duplicate action and rejected approval events;
7. the synthetic session was closed and no pending approval remained.

No Codex turn, e-mail, WhatsApp message, read marker or other external mutation
was executed.

## 8. Integrated repository state after deployment

The production deployment was followed by a source-only reconciliation with the
newer transferred `main`. Merge SHA
`6d5b964178f28319081b5ff057616a4979a5efba`, tree
`4d88b344bcc68c3b62cfb8611a2cec6b9d2e6f79`, has parents `b5458c0` and
`04d49d4`. It preserves this production correction plus the dynamic multi-inbox
candidate, dedicated image runner and repository-transfer records.

The combined source passed 266 Agent Core/Gemini/Edge tests, 112 frontend tests,
TypeScript, Vite/PWA, Ruff check and Ruff format over 1,517 Python files. The
merge itself was not deployed and did not execute an external mutation.

## 9. Explicit production limitations

Production image `846127c` is not full WhatsApp Web parity and is not yet
multi-inbox:

- The deployed OpenJarvis selects one authorized inbox per channel; it does not
  automatically gain access to every active or future AceleraChat inbox.
- WhatsApp contextual reply, reaction, provider read receipt and media send are
  not exposed by the deployed 16-tool catalog.
- The selected active WhatsApp inbox is ID 20 and selected e-mail inbox is ID 16.
- A real approved same-task Codex turn remains an operator acceptance test; it
  was deliberately not executed during release smoke.

Integrated source SHA `6d5b964` contains the dynamic 24-tool implementation for
all authorized inboxes plus contextual reply, reaction, provider read receipt
and HTTPS media. Those capabilities are source-validated but still require a
new immutable image, production preflight, backup, deploy and controlled smoke.
They must not be inferred from the deployed “16 of 16 tools available”.

## 10. Rollback

Primary rollback target:

```text
openjarvis-core:2ed693755e1cf0a21a0cb7cb704fbdd3c4294415
```

Rollback procedure:

1. record current image, health and both database integrity results;
2. restore the backed-up Compose and private environment files without printing
   their contents;
3. select the previous immutable image and recreate only the OpenJarvis Core;
4. require container health, public health/TLS and Edge reconnect;
5. restore the database backup only if an independently verified database fault
   requires it; the release introduced no destructive migration;
6. retain the failed image, source archive, manifest and logs for audit.

The new operational-event database is additive. The previous image can ignore
it; deletion is neither required nor authorized for rollback.

## 11. Change declaration

- Production deploy: yes, controlled and rollback-capable.
- Database migration: no destructive migration; additive operational database
  created by the new release.
- DNS/OpenResty change: no.
- Credential rotation or disclosure: no.
- GitHub Actions used: none.
- Real Codex delegation: no.
- Real e-mail/WhatsApp mutation: no.
- Publication: one final fast-forward push is permitted after local
  documentation and publication gates. The exact published documentation HEAD
  is recorded in the completion output because a commit cannot contain its own
  future SHA.
