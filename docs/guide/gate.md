# The gate

## What this is

`sstack-gate` is the deterministic checkpoint before review and before a PR. It runs the base
branch's `verify` commands, refuses edits or deletions of protected files, and with `--pr` requires
the before/after evidence a PR needs. Its exit code is the verdict, so `work` cannot mistake a wall of
green prose for a passing check. The full contract is [docs/spec/gate.md](../spec/gate.md).

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
```

The repo must also be registered in `~/.sstack/repos.txt`; `setup` does that. An unregistered repo
exits 2 and runs nothing.

## Run it

```sh
home="${SSTACK_HOME:-$HOME/.sstack}"
mkdir -p "$home" .sstack
git rev-parse --show-toplevel >> "$home/repos.txt"
printf 'verify = "true"\n' > .sstack/project.toml
sstack-gate
run=$(mktemp -d)
sstack-gate --run "$run"
head -1 "$run/gate/1.md"
```

```text
# expect
GATE: PASS
GATE: PASS
```

Without `--run`, the verdict goes to stdout and nothing is written. With `--run <run>`, the gate
writes `<run>/gate/1.md` and `1.log`, then numbers the next call `2`, and so on. `--pr` shares that
numbering and writes `<n>-pr.md` and `<n>-pr.log`.

## What it checks

- **Config.** `verify` and `protected` come from the base branch's raw `.sstack/project.toml`. If the
  base has no such file, the working-tree copy is used and the verdict says so. The local layer is
  never read, so an edited `verify` cannot judge itself.
- **Changes.** The diff is against the merge base and includes the working tree and untracked files.
  A rename is a delete plus an add.
- **Protected files.** Any modified or deleted file matching `protected`, or
  `.sstack/project.toml`, fails the gate. New files under a protected glob pass.
- **The run manifest.** With `--run`, the gate checks every repository file listed in
  `<run>/protected/SHA256SUMS` against its recorded sha256. `work` writes that file in the `plan`
  step and restores protected files before the `gate` step in `restore` mode.
- **PR evidence.** With `--pr`, frontend and mobile changes need an `after-*` image or video; backend
  and security changes need an `after-*.mmd` diagram. Every after file needs a matching before file.
  Test files and docs/config-only changes owe nothing.

`media/no-before.md` waives one missing before side and its reason is quoted. `media/skip.md` waives
the whole evidence check with a reason; the verdict says `MEDIA WAIVED: <reason>` and still checks
`verify` and protected files.

## Merge verdict

`sstack-gate --merge <pr> --run <run>` answers one question for `overnight`: may this PR be merged
under the repo's `[overnight]` policy? It needs `--run`, because the verdict is written there, and
cannot be combined with `--pr`. The first line is `MERGE` or `HOLD: <reason>; <reason>` and the exit
code matches: 0 may merge, 1 stays open, 2 is a setup error (no `gh`, a failed call, an untrusted
repo) with nothing written.

The policy is layered like the rest of the config, with one difference: the repo layer comes from the
base branch, so a branch cannot loosen the policy it is merged under. A repo `.sstack/config.toml`
that the base branch does not have is used from the working tree and labelled; one this branch added
(tracked in `HEAD`, absent from base) is ignored and labelled too. The local layer still counts,
because it is machine-only, unless git tracks anything under `.sstack/local` or either `.sstack` or
`.sstack/local` is a symlink: then a branch could carry it, so it is ignored.

`HOLD` reasons, in the order they are printed:

- `merge` is not `"policy"`, so the default `"never"` holds every PR.
- the run has no `--pr` verdict, or its latest one is not `GATE: PASS`.
- that verdict's `- Head:` line is not the PR's head commit, or says `(dirty)`. Every gate verdict
  records the commit it checked, so an old run or a push after the gate cannot merge.
- the review step is not `pass`, the PR head's change is not the one it recorded (`patch`, a
  sha256 of the diff from the merge base; a rebase onto unrelated files keeps it, any edit including
  whitespace does not), or its score is below `merge_min_score`.
- CI is not green: `ci: failed` when a finished check run is not `SUCCESS`, `NEUTRAL` or
  `SKIPPED` or a status context is not `SUCCESS`/`PENDING`/`EXPECTED`; otherwise `ci: pending` while
  any check is unfinished. An empty rollup is green.
- the PR does not merge cleanly with the base.
- additions + deletions exceed `max_diff_lines`.
- a changed file matches a `never_merge` glob.
- the PR is a draft.
- `<run>/assumptions.md` is not empty and `merge_with_assumptions` is false.
- the PR targets a branch other than the repo's default branch.

One `gh pr view` fills all of it: draft state, mergeability, base branch, checks and files. The
command merges nothing and pushes nothing; `overnight` runs `gh pr merge` itself, and only on
`MERGE`. The keys and their defaults are the `[overnight]` table in
[configuration.md](configuration.md#file-schemas).

## In `work`

The `gate` step is a command step: its `run.sh` is `sstack-gate --run "$SSTACK_RUN"`, so
`sstack-workflow run gate --run <run>` executes it from the repo root and records pass or fail. A
FAIL routes to the step's `on_fail` (built in: `implement`) with the verdict file; no review runs on
a failing gate. The `pr` step then rebases, re-runs the answer key (the gate runs only `verify`), and
runs `sstack-gate --run <run> --pr`; it does not ask for the user's yes until that passes. If it
prints a `MEDIA WAIVED` line, show that line at the gate.

## How to change this

- Contract: [docs/spec/gate.md](../spec/gate.md); code: `lib/sstack_gate.py`, `bin/sstack-gate`.
- Config keys: `verify` and `protected` in [configuration.md](configuration.md#file-schemas).
- Skill text: `skills/work/steps.md` (`plan`, `gate`, `review`, `pr`); the step config:
  `defaults/steps/<name>/step.toml` ([workflow.md](workflow.md)); evidence rules in
  `skills/work/testing.md`.
- Tests: `python3 -m unittest discover -s tests -p test_gate.py`, then the full suite.
