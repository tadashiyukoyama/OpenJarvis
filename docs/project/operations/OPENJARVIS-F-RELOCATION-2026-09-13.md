# OpenJarvis local relocation to F: — 2026-09-13

Status: COMPLETED WITH FINAL-SYNC PREREQUISITE
Owner: Cesar Yukoyama / Codex
Source snapshot: `D:\dev\workspaces\openjarvis`
Source branch: `fix/codex-event-driven-contact-reconcile`
Source SHA: `562c14b6b6cfa9661e2a56b6cf46280c88749762`
Target root: `F:\OpenJarvis`
Target branch: `codex/local-f-relocation`
Path-migration commit: `6a07d0ffa0ea233c218aa646b2647158ea90a607`
Path-migration tree: `694d14b7e8467d2e2fae4db318a74e8b3bd44cc4`

## Scope

This was a local filesystem relocation only. The repository, documentation,
ignored runtime, databases, logs, WhatsApp/Baileys state, local caches,
artifacts, Codex home and credentials were copied to F:. The operator requested
the plain directory `F:\OpenJarvis\credenciais`; no additional ACL hardening
was introduced. Secret values were not printed or added to documentation.

The D: source and runtime remain intact as rollback copies. No GitHub, VPS,
DNS, TLS, deployment, migration, tunnel configuration or external message/e-mail
operation was performed.

## Target layout

| Area | F: location | Result |
|---|---|---|
| Git repository | `F:\OpenJarvis` | copied and checked out on a task branch |
| Workspace credentials | `F:\OpenJarvis\credenciais\workspace` | copied; ignored |
| Runtime credentials | `F:\OpenJarvis\credenciais\runtime` | copied; ignored |
| Runtime state | `F:\OpenJarvis\runtime` | copied without duplicating `private` |
| Codex home | `F:\OpenJarvis\codex-home\.codex` | copied; internal junction restored |
| Cache/artifacts | `F:\OpenJarvis\cache`, `F:\OpenJarvis\artifacts` | copied |
| Models/toolchains/worktrees | under `F:\OpenJarvis` | created as managed empty roots |

The local user variables `OPENJARVIS_HOME`, `OPENJARVIS_RUNTIME_ROOT`,
`OPENJARVIS_EDGE_PROJECT_ROOTS`, `OPENJARVIS_WORKSPACE_ROOT` and `CODEX_HOME`
now point to F:. The Edge Worker scheduled task was reinstalled with the F:
launcher and is `Ready`; it was deliberately left stopped because the local
stack was not started by this migration.

## Copy evidence

- Repository: `111,932` files, `1.540 GiB`, robocopy exit `3`, zero failed files.
- Runtime: `36,574` files, `2.565 GiB`, robocopy exit `1`, zero failed files.
- Workspace/runtime credential trees: robocopy exit `1` for each, zero failed
  files; values were not inspected.
- Codex home: `12,796` files, `6.100 GiB`, robocopy exit `1`, zero failed files.
- Junctions reconstructed: `2,625` internal links across repository, runtime
  and Codex home.
- External dependency: the seven-file `ana-crm` skill originally targeted
  `D:\JarvisCRM-V2\codex-agent\ana-crm`; it was copied to
  `F:\OpenJarvis\external\ana-crm` and its Codex-home junction now targets F:.
- Copy logs: `F:\OpenJarvis\migration\repo-copy.log`,
  `runtime-copy.log`, `credentials-workspace-copy.log`,
  `credentials-runtime-copy.log`, `codex-home-copy.log` and
  `codex-home-delta.log`, `ana-crm-copy.log`. The open-session delta copied
  `17` changed files with `0` failures and preserved `4` destination extras.

## Validation

- `validate-local-boundaries.ps1`: PASS; eight configured paths on F and
  internal junction targets contained by the workspace.
- `disk-guard.ps1`: PASS; F: had `102,498,078,720` bytes free at validation.
- `install-local-stack.ps1 -ValidateOnly`: PASS; Python environment, frontend,
  Cloudflared and Codex package detected; `uv` remains an external prerequisite.
- Workspace foundation: `15 passed, 0 failed`.
- SQLite `quick_check`: PASS for eight canonical databases, including
  knowledge, Jarvis Agent, WhatsApp, operational events and Edge Worker stores.
- Seven source/target canonical database pairs preserved byte size and SHA-256.
- A full test run created test-only changes in two local SQLite files; with the
  stack stopped, those exact files were restored from D: and the generated
  sidecars removed. The final seven byte-comparable pairs preserve size and
  SHA-256; the WAL-backed WhatsApp runtime database has equal logical table
  counts and passes `quick_check` on both sides.
- PowerShell parsing and `git diff --check`: PASS.

## Final-sync prerequisite

The Codex Desktop process was intentionally not closed by this migration. Its
home was copied as a safe point-in-time snapshot while the application could
still be writing new history. Before formatting D:, close Codex normally and
run a final non-destructive delta copy of `D:\dev\codex-home\.codex` to
`F:\OpenJarvis\codex-home\.codex`, then verify the target opens with the F:
`CODEX_HOME`. Do not delete D: until that final sync and a new Codex startup
smoke pass.

The external source `D:\JarvisCRM-V2\codex-agent\ana-crm` remains untouched;
the F: Codex profile uses the copied external skill under the ignored
`F:\OpenJarvis\external\ana-crm` path. The separate JarvisCRM project itself
was not migrated by this OpenJarvis relocation.

## Rollback and operational status

Rollback is the preserved D: source/runtime plus the original user-level
configuration values, restored only by an explicit operator decision. The
current F: branch contains the path migration; copied ignored data is outside
Git. Local ports `5173`, `8127`, `8131` and `8140` were not started here, so
this report does not claim the application is online. The next safe action is
to run the F: launcher, validate health and perform the existing read-only
smoke; do not format D: before the final-sync prerequisite is complete.
