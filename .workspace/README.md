# Workspace foundation

This directory contains portable project identity, policies, schemas and
templates. Machine-specific state belongs under .workspace/local and is
ignored by Git.

The canonical workspace is represented by OPENJARVIS_WORKSPACE_ROOT. OJ0
established local staging and OJ1 promoted the controlled upstream checkout
to the canonical Git root. Dependencies, execution, models, worktrees and
external services remain separately gated.
