---
summary: How the Orca hook drives Orca workers, and the CLI traps behind its old headless fallback
paths: defaults/ades/orca.hook, tests/fakes/fake_cli.py
updated: 7e1246d
---
# Orca ADE

- The hook's whole lifecycle is `worker-start` (it creates the Run and the Task), `worker-show`
  polled until `stage` is `settled`, and `worker-stop` on timeout. There is no `task-create`
  step and no `check --task`.
- Never poll `orca orchestration check` from a hook: it reads the coordinator's own mailbox and
  marks the batch handled, so the coordinator loses the worker's `worker_done`. `worker-show`
  is read-only.
- A worker's `state` is `ready` while it runs; only `stage: settled` means done.
- Children run with `--worktree current`. sstack's `isolates()` only knows tool ADEs, so a hook
  child is treated like a shell child in this checkout under the write lock; a `new-child`
  worktree would leave the gate looking at an unchanged tree.
- Any delegate failure falls back to headless silently apart from one stderr note
  (`hook delegate exit 1; running headless`). The fake CLI once copied the hook's invented flags,
  so the tests passed while every live dispatch fell back. Check the fake against `--help`.
- Tests run inside an Orca session inherit `ORCA_AGENT_SESSION_ID`; two `test_ui` ADE tests then
  detect orca. Run the suite with `env -u ORCA_AGENT_SESSION_ID`.
