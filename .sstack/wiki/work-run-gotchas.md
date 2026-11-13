---
summary: Traps hit while driving a work run with routed children (protected manifest paths, plan-mode reports, worktree lanes)
paths: skills/work/**, bin/sstack-gate, bin/sstack-dispatch
updated: 8f32a81
---
# Work run gotchas

- `protected/SHA256SUMS` must list repo-relative paths
  (`.sstack/runs/<run>/acceptance.py`), not paths relative to `protected/`; otherwise the gate
  fails with "protected file is missing".
- Children in plan mode can't write their `--report` file. Write it from the child's final message,
  then `sstack-dispatch record`.
- A write child with `isolation: worktree` must be told to edit only its own worktree and to read run
  files by absolute path. "Work ONLY in <parent path>" contradicts the isolation and confuses it.
- Bring a worktree child's diff back with `git apply` of a patch; compare the parent's
  `git status` before and after to catch a child that wrote to the parent.

See [dashboard-file-safety](dashboard-file-safety.md) for what that run's review caught.
