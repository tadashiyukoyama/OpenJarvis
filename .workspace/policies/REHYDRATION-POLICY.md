# Rehydration policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: unknown
Supersedes: none
Superseded by: none

Read AGENTS.md, portable identity, local configuration when present,
current state, document index, task document and only then the real Git and
code. rehydrate-project.ps1 validates the foundation in place and never
clones, downloads, installs, starts services or creates worktrees.

The portable identity contains no machine-specific absolute Windows paths.
Machine paths remain in the ignored local configuration.
