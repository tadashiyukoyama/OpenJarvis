# OpenJarvis controlled release evidence — 2026-08-19

Status: CANONICAL EVIDENCE
Owner: Cesar Yukoyama / Codex
Applicable local code SHA: `1ecb90ac6191c27501c2ca497c2deecdf5bad8e0`
Applicable local code tree: `b1196b73f2f27fec596d4458ae79a9cb05b725d1`
Branch: `codex/edge-live-relay-release`

## Scope and safety

This record covers the controlled OpenJarvis Core deployment, Windows Edge
activation, shared Codex runtime and local MCP read-only acceptance. It did not
authorize or execute a new Codex turn, e-mail send, WhatsApp send, provider
reconnection, credential rotation or AceleraChat migration. External mutations
remained disabled.

## Source and publication

- Private repository: `tadashiyukoyama/openjarvis-codex`.
- Production-source baseline: `9874381c9df924e9d439ecb958761a6df27586b1`.
- Previously published documentation HEAD and Core release:
  `2ed693755e1cf0a21a0cb7cb704fbdd3c4294415`.
- Local MCP hotfix: `1ecb90ac6191c27501c2ca497c2deecdf5bad8e0`.
- The hotfix changes only MCP effect validation, a Windows launcher example and
  regression tests. Core API, Edge protocol and database schema are unchanged,
  so the validated Core image remains at `2ed6937`.

## VPS evidence and rollback

- Active image tag:
  `openjarvis-core:2ed693755e1cf0a21a0cb7cb704fbdd3c4294415`.
- Active image ID:
  `sha256:146c1cf9c5bfa991e8c4f0b5113d4bde286a8f3b3b0c5138c2ce020e466c8664`.
- Source archive SHA-256:
  `4dbb81e4ef7371ede071939ee23cdd798682aa160cfa4c084b91b62b2e5f7c4b`.
- PostgreSQL was not used by OpenJarvis Core; its SQLite backup is
  `/opt/openjarvis/backups/jarvis-agent-20260819T184526Z-3586569fe597943baa990dfb18fa5f7a7d2c9b69.sqlite3`.
- Backup SHA-256:
  `bc3fb12f1ef8e41d7c9f18981ef1a828d94d8ae2dd88666ac7b27747c38731bd`.
- Previous rollback image:
  `openjarvis-core:3586569fe597943baa990dfb18fa5f7a7d2c9b69`.
- Previous image ID:
  `sha256:2a65d953c11778bd9d11554e8827c74425907bbc4e9d181ce5c05c72d72d8543`.

The Core container passed health checks as non-root UID 10001 with a read-only
root filesystem. The release retained `external_mutations=false`.

## Windows evidence and rollback

- Stable runtime path: `D:\dev\workspaces\openjarvis`.
- Stable local runtime SHA after the hotfix: `1ecb90a`.
- Prior local runtime SHA: `2ed6937`.
- Edge database backup:
  `D:\dev\runtime\openjarvis\backups\edge-worker-20260819T185114Z-before-2ed6937\edge-worker.sqlite3`.
- Edge backup SHA-256:
  `bc4aa51c60fc889f89863e919717318726f2684638fc675041076a6f86b6e029`.
- Preserved untracked items: `.manus-audit/`, `frontend/pnpm-lock.yaml` and
  `node_modules/`.

After a full Windows reboot, the limited `OpenJarvis Edge Worker` scheduled task
was `Running`; exactly one Codex app-server listened on `127.0.0.1:8131`; and no
private second listener was present. Local source rollback to `2ed6937` must also
disable the MCP server, because that older facade contains the annotation defect.

## Tests and live read-only evidence

- 538 directed Python tests and 4 subtests passed.
- 152 MCP tests passed.
- Ruff check/format, Python compilation, TOML parsing and `git diff --check`
  passed for the hotfix.
- MCP initialized using the exact absolute command configured for Codex.
- Six tools were listed; all were read-only, non-destructive and non-Codex.
- Real `jarvis_read_operational_audit` and `whatsapp_get_status` calls completed.
- WhatsApp correctly reported `source_disconnected`; no reconnect was attempted.
- Real `codex.status` completed in 882 ms and reported the executing task busy.
- Bounded `codex.history` returned three messages and matched the current reboot
  marker without printing message content.
- The matching thread hash had 83 recent live events with `item_started`,
  `item_completed` and `text_delta` types.

No real message, e-mail or Codex turn was sent by these tests.

## Remaining explicit gates

- one user-authorized delegated turn in the selected existing Codex task;
- visual OpenJarvis proof on desktop and tablet;
- any provider mutation or real e-mail/WhatsApp send;
- WhatsApp reconnection after the provider restriction is independently safe.
