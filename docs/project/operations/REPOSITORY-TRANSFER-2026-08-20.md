# Repository transfer — 2026-08-20

## Scope

- Source: `tadashiyukoyama/openjarvis-codex`.
- Destination: `cesaryukoyama28-eng/openjarvis-codex`.
- Visibility preserved: private.
- Default branch preserved: `main`.
- SHA immediately before and after transfer:
  `f6a0a17d6415ede65b7582e62686d1003b59fe20`.

## Evidence

- Git history was preserved and the previous URL redirects to the new owner.
- The `github-pages` environment was preserved.
- The `vps10056-openjarvis` runner remained online and completed isolated smoke
  run `32339747103` after the transfer.
- Runner scripts accept the legacy `systemd` unit name preserved by the
  transfer and use the new owner name for future installations.
- No deployment, production migration, credential rotation, message or e-mail
  mutation was executed.

## GHCR

No `openjarvis-codex` container package existed in the previous personal
namespace at transfer time. Future immutable images therefore use
`ghcr.io/cesaryukoyama28-eng/openjarvis-codex:<full-git-sha>`. Publication still
requires the existing workflow gates; this transfer did not publish an image.

## Rollback

An accepted ownership transfer has no automatic rollback. Reverting ownership
requires a new transfer. The pre-transfer commit remains identified by the SHA
above.
