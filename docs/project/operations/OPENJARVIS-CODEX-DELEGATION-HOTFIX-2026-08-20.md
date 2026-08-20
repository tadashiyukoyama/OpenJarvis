# OpenJarvis Codex delegation hotfix — 2026-08-20

Status: PRODUCTION DEPLOYED AND AUDITED
Owner: Cesar Yukoyama / Codex
Branch: `codex/edge-live-relay-release`
Functional SHA: `3d311bcba5a6ce3629458ab0a8b8515a06913d71`
Functional tree: `216231b6c10c227d3b897cdbe748c13b052b3de7`
Publication target: private `cesaryukoyama28-eng/openjarvis-codex`, branch `main`

## Incident

The operator requested a Codex delegation through Jarvis and approved the
visible proposal. Production persisted all governance transitions correctly,
but the action then failed before reaching the Windows Edge Worker:

- action: `act_46fd626902d64b9ea3ce8f52a3052e87`;
- approval: `apr_83bf5fcf7c794c42a46cc6f4d0c977d5`, decision `approve`;
- job: `job_6c8913c6b5e64003bcbed98feeeb449c`;
- terminal state: `FAILED`;
- public error: `INVALID_REQUEST`;
- persisted summary: `Os argumentos da ferramenta Codex são inválidos.`;
- no `codex.delegate` attempt was created on the Edge Worker.

The failure was deterministic. `EdgeCodexAdapter.prepare()` correctly resolved
the approved public command into the internal payload containing
`project_cwd`, `thread_id` and `command`. `execute()` then incorrectly validated
that internal payload with the public Gemini argument model, whose
`extra="forbid"` contract accepts only `command` and `limit`. The server rejected
its own trusted fields before offering the job to Edge.

## Correction

The adapter now has separate closed models for the two trust boundaries:

- the public model validates Gemini arguments;
- the internal delegate model validates the server-resolved project, task and
  exact command;
- the internal model normalizes whitespace, bounds all fields and requires an
  absolute project path;
- preflight and execution validate the same internal payload;
- the digest and Edge job use the normalized internal payload.

The new regression test covers both the adapter boundary and the complete
`propose -> visual approve -> asynchronous job -> Edge adapter` transition.

## Validation

| Gate | Result |
|---|---|
| Focused delegation, jobs and Edge runtime | 10 passed |
| Agent Core, Edge Worker and MCP suites | 410 passed; 5 upstream deprecation warnings |
| Ruff check and format | passed |
| Patch whitespace | `git diff --check` passed |
| Publication scanner | PASS; 2,444 tracked files; no forbidden path or detected secret |
| Source archive | 2,755 tracked entries; zero forbidden/private entries |
| Image-level regression | PASS with `--network none`; zero external calls |

Preserved untracked operator files were not included in the commit, archive or
image: `.manus-audit/`, `frontend/pnpm-lock.yaml` and `node_modules/`.

## Artifact and rollback identity

| Item | Value |
|---|---|
| Source archive | `/opt/openjarvis/backups/source-3d311bcba5a6ce3629458ab0a8b8515a06913d71.tar.gz` |
| Archive bytes | `43186558` |
| Archive SHA-256 | `45d31a8c8a6bdd0a6426d84e4b8ce98bbd03ef06be41e772c72bf7c712be7b9f` |
| Production image | `openjarvis-core:3d311bcba5a6ce3629458ab0a8b8515a06913d71` |
| Image ID | `sha256:4b07876940850bbd5da27fcf32b57a6bec076f47d594c95269ad9d77e686923c` |
| Image size | `177979057` bytes |
| Rollback image | `openjarvis-core:846127cfa76680d11dd686ea052f5b7fdc7c4818` |
| Deployed at | `2026-08-20T20:45:22Z` |

Validated backups created before replacement:

- `/opt/openjarvis/backups/jarvis-agent-20260820T203820Z-846127cfa76680d11dd686ea052f5b7fdc7c4818.sqlite3`
  — SHA-256 `041a0acc6271cc15a4cdf6cc886717605323f9df7322472686615ad27c489ccc`;
- `/opt/openjarvis/backups/operational-events-20260820T203820Z-846127cfa76680d11dd686ea052f5b7fdc7c4818.sqlite3`
  — SHA-256 `b72ea1c8cfb1e41e01fced1bb03a81c79f0edc6068f7e1088d9d1f3ccb9fbd28`;
- Compose SHA-256
  `1c91bbbc492c3a99d3374a76ca757231143a6683c62d07a669bdaea0a2575b51`;
- private environment backup SHA-256
  `e0d9bc52e1f395291648fc47e4ae6bea135745d1235a0f505a397de774cc6838`.

Both database backups and both live databases returned `quick_check=ok`.
No credential value is present in this report.

## Deployment evidence

The first controlled activation intentionally rolled back when an audit
assertion used the non-canonical capability name `whatsapp.mark_read`. The
runtime correctly exposes the two explicit contracts
`whatsapp.mark_read_provider` and `whatsapp.mark_read_internal`. The rollback
restored image `846127c...` and reached `healthy` before the corrected gate was
run.

The second controlled activation passed:

- public HTTPS health: `{"status":"ok"}` with certificate verification;
- container health: `healthy`, restart count `0`;
- Edge device: `ONLINE`, no last error;
- catalog: 24 tools, 24 available, zero blocked;
- Codex delegation and WhatsApp reply, reaction, provider/internal mark-read and
  HTTPS media contracts present;
- no error/critical/traceback line in the post-deploy container audit;
- original failed action preserved for traceability;
- zero new real Codex delegation jobs during build, deploy and smoke;
- zero e-mail or WhatsApp mutations during this release.

The production image includes the previously integrated dynamic AceleraChat
catalog. This release verifies its availability, not a real provider mutation.

## Rollback

If the operator acceptance test exposes a regression:

1. preserve the failed action/job/event evidence and current image identity;
2. set `OPENJARVIS_IMAGE_TAG` to
   `846127cfa76680d11dd686ea052f5b7fdc7c4818`;
3. recreate only the `core` service with the existing Compose file;
4. require container health, public HTTPS health and Edge `ONLINE`;
5. retain the additive databases unless an independently verified database
   fault requires restoring the validated backups.

No destructive migration, DNS/TLS change, credential rotation, GitHub Action,
real Codex turn or provider mutation was part of this hotfix.
