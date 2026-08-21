# OpenJarvis contact and Codex reconciliation release - 2026-08-20

Status: CANONICAL EVIDENCE
Owner: Cesar Yukoyama / Codex
OpenJarvis functional SHA: `262f7b4f3487c22f7c5d4ca098844c27277b2d3f`
AceleraChat functional SHA: `1febefe0714e19851cb51c7db5c1a7394fc03d8d`
Documentation HEAD: the commit containing this report

## Outcome

The contact reported as `PROVIDER_RESPONSE_INVALID` had actually been created
by AceleraChat. The response projected the pre-trigger Active Record instance,
so the PostgreSQL-assigned public conversation ID was still null in the
immediate HTTP response. A later read returned the valid resource.

AceleraChat now presents a fresh persisted conversation after creation. The
OpenJarvis adapter also treats an invalid or unknown create response as
ambiguous: it performs one read-only reconciliation and never repeats the
POST. The previously created contact remains intact and was recovered through
the production contract with contact ID 401, conversation ID 196 and inbox 20.

The Codex Desktop freeze was independent of contact persistence. The selected
task rollout was approximately 345 MB with more than 81,000 JSONL records.
The previous relay repeatedly reconstructed its history while a turn was
active. Completion is now event-driven; only one bounded
`thread/turns/list(limit=5, sortDirection=desc, itemsView=full)` reconciliation
is allowed at the caller deadline if a terminal notification is lost.

After the corrected Edge Worker started at `2026-08-21T01:37:28Z`, 177 current
Codex Desktop log records contained zero `thread/read`, zero
`thread/turns/list`, zero `ECONNREFUSED` and zero non-null app-server errors.

## Inbox authority

Production account 1 is configured with:

- `inbox_access_mode=all_account`;
- no fixed inbox allowlist;
- administrator service user;
- four effective inboxes out of four account inboxes;
- valid configuration with no validation errors.

`all_account` resolves the account inbox relation at request time. New inboxes
therefore enter the OpenJarvis scope without editing a stored ID list. Provider
capability and connection checks still decide whether an action is executable.

## Validation

- OpenJarvis CI run `32435673489`: success.
- OpenJarvis image run `32435673474`: success.
- AceleraChat image run `32434857798`: success.
- AceleraChat deploy run `32435736232`: success.
- OpenJarvis Core: healthy, zero restarts and zero recent error signatures.
- AceleraChat Rails: healthy on SHA `1febefe`.
- Edge device `cesar-codex-desktop-01`: online with fresh heartbeats.
- Contact lookup through the real OpenJarvis adapter: exact match and valid
  Pydantic contact/conversation contracts.
- No WhatsApp message, e-mail, repeated contact mutation or Codex turn was
  executed by the release validation.

## Production identity and rollback

OpenJarvis production image:

- tag: `openjarvis-core:262f7b4f3487c22f7c5d4ca098844c27277b2d3f`;
- image ID:
  `sha256:0fa4df3f9c2eb15abddd55086e8e1c02c284ca3d40facc1a79e88dc4ba8e0e21`;
- GHCR digest:
  `sha256:4837b9517e98a56d03b041ac60a0e341e8d090ae30474126bb19ad618df2d9a4`.

AceleraChat production image digest:
`sha256:cb08ebbcf8c610774cece93b56e54c6623d640a81cb419bd7c745d2d893bd683`.

Rollback targets:

- OpenJarvis: `openjarvis-core:33a12d4020ac2b0325359ac5c1c3bd667a8db622`;
- AceleraChat: `a01903b9d38377ea97bb07405d8ac1fa62edebd4`.

The verified source archive remains at
`/opt/openjarvis/backups/source-262f7b4f3487c22f7c5d4ca098844c27277b2d3f.tar.gz`,
SHA-256
`68101d0eb9e81211c678aff428eb733c72cf438ef8deaba65a7a6e32a61945e9`.
The temporary 108 MB build directory was removed after verification; the
archive, prior image and timestamped database/configuration backups remain.

The canonical VPS manifest is `/opt/openjarvis/release-manifest.json`; its
SHA-256 is
`4296d675591b727fbe4489e863a0df47cc239985e8afef8202cf5eef8d791b51`.
No migration or credential rotation was required.
