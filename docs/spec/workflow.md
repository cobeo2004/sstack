# Workflow contract — step folders

Owner: `lib/sstack_config.py` (`steps()`, `source()`), `lib/sstack_workflow.py`,
`bin/sstack-workflow`. Checked by `tests/test_workflow.py`, `tests/test_doctor.py`.

The workflow is a set of step folders `steps/<name>/`, one per step, in every config layer
([config.md](config.md)). There is no `workflow.toml`: order, gates and caps are per-step keys.
`sstack-workflow` resolves the chain, tracks a run's place in it and runs command steps. It never
launches an agent — the agent follows the chain the tool prints, and stops where it says `GATE`.

## Step folder

```
<layer>/steps/<name>/
  step.toml    the step's keys, merged per key across layers (a nearer layer wins one key at a time)
  brief.md     a role step's brief: whole from the nearest layer that has one
  run.sh       a command step: whole from the nearest layer that has one, executable, exit 0 = pass
```

A layer may hold only some of a step's files: `~/.sstack/steps/review/step.toml` sets one key for
every repo, and `steps/dmm/brief.md` in a repo re-lenses a step whose `step.toml` lives in the home
layer. `enabled = false` in a nearer layer drops the step.

## `step.toml`

| key | default | meaning |
|---|---|---|
| `after` | `""` | the step this one sits immediately after; `""` is the first step (exactly one) |
| `role` | — | the role that runs it (`roles/<role>.toml`, docs/spec/config.md) |
| `gate` | `false` | stop for the user's explicit yes after this step (`pr` is always `true`) |
| `on_fail` | — | where a fail goes; absent → stop and ask |
| `max_loops` | `rules.loop_guard` (2) | fails of this step before `STOP: ask user` |
| `max_agents` | `1` | `0` = inline (no subagent), `1` = no concurrency, `N` = a cap ≤ `rules.max_parallel` |
| `min_score` | — | `1..10`; `done <step> --findings` below it fails the step |
| `enabled` | `true` | `false` drops the step from the chain |

```toml
# .sstack/steps/review/step.toml — keep the default role and route; raise only the bar
min_score = 7
```

## Kinds

The file present decides the kind: `run.sh` → **command** step, `brief.md` → **role** step. A step
with neither is **inline**: the orchestrator runs it itself, as `pr` ("open the PR") does. Built-in
role steps carry no `brief.md` — the orchestrator writes the task's brief, as before — so their
`role` key is what makes them role steps.

A step that does not ship in the template `defaults/steps/` (a custom step) needs exactly one of `brief.md`
(plus `role`) or `run.sh`: that is a doctor FAIL, as is naming no `role` for a `brief.md`.

## Order

The chain starts at the one step whose `after` is `""`. A step is inserted immediately after its
`after` target; steps inserted after the same target run by name, before that target's declared
successor. So `steps/dmm/{step.toml,run.sh}` with `after = "implement"` gives

```
recon → plan → implement → dmm → gate → review → pr
```

A step whose `after` names a disabled step takes that step's `after`, transitively: disabling the
built-in `plan` gives `recon → implement → gate → review → pr`. Two first steps or a cycle is a
doctor FAIL; `show` then lists the steps it could not place after the chain, so nothing goes missing.

## Built-in steps (`defaults/steps/`)

Reproducing the phases the `work` skill used to hard-code:

| step | `after` | kind | `gate` | `on_fail` | `max_agents` | other |
|---|---|---|---|---|---|---|
| `recon` | `""` | role `investigate` | true | — | 3 | |
| `plan` | `recon` | role `plan` | true | — | 2 | |
| `implement` | `plan` | role `implement` | false | — | 1 | |
| `gate` | `implement` | `run.sh` → `sstack-gate --run "$SSTACK_RUN"` | false | `implement` | 0 | |
| `review` | `gate` | role `review` | true | `implement` | 2 | `min_score = 5` |
| `pr` | `review` | inline (orchestrator) | true (locked) | — | 0 | |

## `<run>/workflow.json`

The tracker's whole state; one file per run folder, written by `done` and `run`:

```json
{"current": "review", "steps": {
  "implement": {"status": "pass", "loops": 0, "score": null},
  "review": {"status": "fail", "loops": 1, "score": 4}}}
```

`status` is `pass`, `fail` or `null`; `loops` counts the step's fails; `score` is the recomputed
review score (`null` for every step without `--findings`). `progress.md` gains one line per
`done`/`run` (`implement: pass`, `review: fail (loop 1/2)`).

## `sstack-workflow` (CLI)

```
sstack-workflow show [--json]
sstack-workflow status --run <run>
sstack-workflow done <step> [--fail] [--findings <json>] --run <run>
sstack-workflow run <step> --run <run>
```

`show` prints the chain with each step's kind, role, gate, `on_fail`, caps and the layer of every
key and file, plus `disabled: …` for steps dropped by `enabled = false`. `--json` prints

```json
{"chain": ["recon", "…"],
 "steps": {"recon": {"role": "investigate", "gate": true, "on_fail": null, "max_loops": 2,
                     "max_agents": 3, "min_score": null, "kind": "role", "brief": null, "run": null,
                     "source": {"after": "home", "role": "home"}}}}
```

`status` prints `at: <current step>` and one line per step with its status, loops and score.

`done` records a result and prints what happens next, one line per outcome:

| outcome | prints | exit |
|---|---|---|
| pass, `gate = true` | `GATE: wait for the user's yes`, then `next: <step>` | 0 |
| pass, `gate = false` | `next: <step>` | 0 |
| pass of the last step | `next: done` | 0 |
| fail with `on_fail`, under the cap | `next: <on_fail>` | 0 |
| fail reaching `max_loops`, or a fail with no `on_fail` | `STOP: ask user` | 2 |
| unknown step, unreadable `--findings` | a message on stderr | 1 |

A run's last step is the last of `show`'s chain. `done` also releases this run's write-lock holders
(`.sstack/runs/implement.lock`, docs/spec/dispatch.md) so the next dispatch into the checkout can
start.

`run` executes the nearest `run.sh` for a command step with `cwd` = the repo root, whatever
directory it is called from, and records its exit like `done` (exit 0 = pass). A `run.sh` whose
source is the `repo` or `local` layer runs only when the checkout is trusted (listed in
`~/.sstack/repos.txt`, like `sstack-gate`); otherwise `run` exits 1 and nothing runs. Its environment adds:

| var | value |
|---|---|
| `SSTACK_RUN` | the run folder (`--run`, absolute) |
| `SSTACK_ROOT` | the repo root (also the `cwd`) |
| `SSTACK_HOME_DIR` | the sstack install root — the clone that holds `bin/` and `defaults/`. **Not** `SSTACK_HOME`, which is the config home |

## Review score (`--findings`)

The review step writes `<run>/<step>/findings.json` — one row per reviewer — and passes its path to
`done review --findings`:

```json
[{"reviewer": "codex/gpt-6.1-sol", "score": 6,
  "findings": [{"severity": "Important", "verified": true},
               {"severity": "Nit", "verified": false}]}]
```

`important` = every finding with `severity = "Important"` that is `verified`, across reviewers. Each
reviewer's score is recomputed after verification, because the tool, not the reviewer, decides what
survived:

| the reviewer's findings | its score becomes |
|---|---|
| a verified Important | `min(score, 6)` |
| every Important dropped, at least one verified finding left | `max(score, 7)` |
| every Important dropped, nothing verified | `10` |
| no Important at all | its own score, unchanged |

`final` = the lowest recomputed score across reviewers. The step fails when `--fail` is given, when
`final < min_score`, or when `important > 0` — a verified Important routes back regardless of the
score. The tool prints `score: <final> (min of <reviewer>=<n>, …; verified Important <n>)` and
stores `final` as the step's `score`, and `patch`: sha256 of the working tree's diff from the merge base, without `index` lines (untracked files included; `null` when git cannot compute it), which
`sstack-gate --merge` compares with the PR (docs/spec/gate.md).

## Doctor rules

`sstack-doctor` prints one `workflow` line (docs/spec/doctor.md):

- **FAIL** — an `after` or `on_fail` naming no step; `on_fail` naming a disabled step; a cycle, or
  two first steps; a custom step with both or neither of `brief.md`/`run.sh`; a `brief.md` without
  `role`; `min_score` outside `1..10`; `pr` with `gate = false` or `enabled = false`.
- **WARN** — `max_agents` above `rules.max_parallel` (`rules.max_parallel` stays the ceiling).
- **PASS** — otherwise; names the resolved chain.

## API

```python
steps(root) -> {name: {"spec": dict, "source": {key or file: layer}, "brief": Path | None,
                       "run": Path | None, "builtin": bool}}
# steps/<name>/ of every layer; step.toml merged per key, brief.md and run.sh whole from the nearest
# layer (run.sh: else the template's), builtin = ships in the template's steps/. Read here, never in load(): load() output is unchanged.
source(root, "steps", "<name>/brief.md") -> (layer, path) | None   # also step.toml, run.sh
resolved(root) -> {"chain": [name], "steps": {name: {…show --json…}}}
# the resolved chain and its steps, with `rules.loop_guard` applied as the default max_loops
```
