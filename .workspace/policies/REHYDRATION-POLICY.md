# Rehydration policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

Read `AGENTS.md`, portable identity, local configuration when present,
current state, document index, task document and only then the real Git and
code. Resolve the root from `OPENJARVIS_WORKSPACE_ROOT`, or from the script
location when the variable is absent. Validate the foundation in place.

Rehydration never clones, downloads, installs, starts services or creates
worktrees. The portable identity contains no machine-specific absolute
Windows paths; concrete machine paths remain in ignored local configuration.
