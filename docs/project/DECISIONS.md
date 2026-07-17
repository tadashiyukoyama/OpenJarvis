# Decisions

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

## OJ0-D01 - Local staging on D

- Decision: establish D:\dev\workspaces\openjarvis as the permanent local
  workspace root.
- Reason: keep project-managed files on D and make rehydration predictable.
- Consequence: machine-specific paths stay in ignored local configuration.
- Evidence: OJ0 preflight and project portable identity.

## OJ0-D02 - No official download in OJ0

- Decision: defer clone, fork and code acquisition until OJ1 is separately
  authorized after this report is reviewed.
- Reason: OJ0 is foundation-only and must not make network changes.
- Consequence: Git root, remotes and source SHAs remain unknown.

## OJ1-D03 - Controlled fork promotion

- Decision: use tadashiyukoyama/OpenJarvis as origin, open-jarvis/OpenJarvis
  as upstream, and promote the verified partial clone to the canonical root.
- Reason: establish the product fork without overwriting upstream files.
- Consequence: the foundation is versioned on
  ops/openjarvis-workspace-foundation at the live SHA
  3000116d181eb69737241c09eaa70d4c65eb80a0.
- Evidence: clone state, collision scan, D: staging hash backup and Git root
  verification.
