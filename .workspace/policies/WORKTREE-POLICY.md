# Worktree policy

Status: CANONICAL
Owner: Cesar Yukoyama / Codex
Last verified: 2026-07-17
Applies to SHA: 3000116d181eb69737241c09eaa70d4c65eb80a0
Supersedes: none
Superseded by: none

There is one canonical Git worktree and at most the configured number of
additional simultaneous worktrees for the whole project. The portable limit
is `maxAdditionalWorktrees` in `.workspace/project.portable.json`. The
machine-specific `worktreesRoot` is read from
`.workspace/local/project.local.json`. No worktree may be inside the Git
root.

Use an additional worktree only for genuine parallel work, an isolated fix or
a separate review. Every additional worktree requires a local ledger entry.
Lifecycle automation remains disabled until the ledger, status and untracked
checks, exclusive-commit disposition, PR/task state, transactional ledger
update and filesystem confirmation are implemented and verified.
