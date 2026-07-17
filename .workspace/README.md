# Workspace foundation

This directory contains portable project identity, policies, schemas and
templates. Machine-specific state belongs under `.workspace/local` and is
ignored by Git.

The canonical workspace is represented by `OPENJARVIS_WORKSPACE_ROOT`.
Concrete machine paths are read from the ignored local configuration. The Git
root is established, while lifecycle automation, dependencies, execution,
models and external services remain separately gated.
