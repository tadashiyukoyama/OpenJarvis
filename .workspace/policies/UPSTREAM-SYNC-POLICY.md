# Upstream synchronization policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

The Git root is established. `origin/main` is the product branch in the
fork, and `upstream/main` represents `open-jarvis/OpenJarvis`. The local main
branch tracks `origin/main`. Technical references use full 40-character SHAs.

Future synchronization is explicit, reviewed and non-automatic. It must
identify the source and destination refs, capture the live source SHA, review
the diff and preserve the fork's project-managed changes. No fetch, pull,
merge, rebase, force push, deploy or other synchronization mutation is
authorized merely by this policy.
