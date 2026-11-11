# The workflow

## What this is

`work` does not hard-code its order. The workflow is a chain of step folders:
`steps/<name>/step.toml`, plus `brief.md` or `run.sh` on a custom step. Folders are
read from the four config layers and merged key by key, so a repo or a user can
add, disable, reorder or re-gate a step without forking a skill. A built-in role
step (recon, plan, implement, review) carries no `brief.md`: `work` writes that
task's brief itself.

`sstack-workflow` resolves the chain (`show`), remembers where a run is
(`status`, `<run>/workflow.json`, one line per step in `progress.md`) and enforces
the loop cap (`done`, `run`). It never launches an agent: the agent reads the chain
and follows it, which is why a step can be a command, a role or something `work`
does inline. The contract is [docs/spec/workflow.md](../spec/workflow.md); the folder layout is part of
[docs/spec/config.md](../spec/config.md).

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
sstack-config sync >/dev/null          # your ~/.sstack profile, as sstack-install creates it
```

## The built-in chain

The template `defaults/steps/<name>/step.toml` ships this (synced into `~/.sstack/steps/`). A repo with no `steps/` of its own
runs exactly this order:

| step | after | kind | gate | on_fail | max_agents | other |
|---|---|---|---|---|---|---|
| `recon` | — | role `investigate` | yes | — | 3 | |
| `plan` | `recon` | role `plan` | yes | — | 2 | |
| `implement` | `plan` | role `implement` | no | — | 1 | |
| `gate` | `implement` | command: `sstack-gate --run "$SSTACK_RUN"` | no | `implement` | 0 | |
| `review` | `gate` | role `review` | yes | `implement` | 2 | `min_score = 5` |
| `pr` | `review` | inline, in this session | yes, locked | — | 0 | can't be disabled |

`max_agents` is how many members one dispatch of that step may run at once: `0`
runs it inline in this session, `1` means no concurrency, `N` is a cap that
`[rules] max_parallel` still limits. What each step does:
[skills/work/steps.md](../../skills/work/steps.md).

## A step folder

```text
<layer>/steps/<name>/
  step.toml     the keys below
  brief.md      role step: the brief dispatch starts from
  run.sh        command step: executed from the repo root; exit 0 passes
```

| key | value |
|---|---|
| `after` | the step this one follows; `""` for the first step. A custom step is inserted immediately after its target; two after the same target order by name |
| `role` | the dispatch role for a role step |
| `gate` | `true` stops for the user's yes after this step |
| `on_fail` | the step a failure routes back to; absent → stop and ask |
| `max_loops` | how many failures of this step before `STOP`; default `[rules] loop_guard` |
| `max_agents` | `0` inline, `1` no concurrency, `N` a cap (≤ `[rules] max_parallel`) |
| `min_score` | the review bar, 1–10, for a step that takes a findings file (review) |
| `enabled` | `false` drops the step from the chain |

How the layers combine:

- `step.toml` merges per key across `~/.sstack/`, `.sstack/`,
  `.sstack/local/`. A repo file with only `min_score = 7` keeps the built-in `role`
  and `on_fail`.
- `brief.md` and `run.sh` each come whole from the nearest layer that has one, so a
  repo can replace a home layer's brief without merging its text. A `run.sh` no layer
  has comes from the template (`gate/run.sh`).
- The file present decides the kind. A step the template does not ship needs exactly
  one of them; a role step also needs `role`.
- A disabled step is bypassed: a step whose `after` names it takes that step's
  `after`, transitively. Disabling `plan` gives `recon implement gate review pr`.

`sstack-doctor` FAILs a bad folder: an `after` or `on_fail` naming no step, a cycle
or two first steps, a custom step with both or neither of `brief.md`/`run.sh`, a role
step without `role`, `pr` with `gate = false` or `enabled = false`, and a
`min_score` outside 1–10. It WARNs when `max_agents` exceeds `[rules] max_parallel`.

## Add a custom step

A repo with a data-migration check between implement and gate:

```sh
mkdir -p .sstack/steps/dmm
printf 'after = "implement"\non_fail = "implement"\n' > .sstack/steps/dmm/step.toml
printf '#!/bin/sh\nset -e\npnpm migration:check\n' > .sstack/steps/dmm/run.sh
chmod +x .sstack/steps/dmm/run.sh
sstack-workflow show --json | python3 -c 'import json, sys; print("chain:", " ".join(json.load(sys.stdin)["chain"]))'
```

```text
# expect
chain: recon plan implement dmm gate review pr
```

Tracking it is the same as any command step; `on_fail = "implement"` sends a
failure back with the script's output, and `max_loops` (default `[rules]
loop_guard`) stops after that many. A `run.sh` from the repo or `local/` layer runs only
in a checkout listed in `~/.sstack/repos.txt`, the same trust `sstack-gate` asks for:

```sh
mkdir -p ~/.sstack && echo "$PWD" >> ~/.sstack/repos.txt
run="$PWD/.sstack/runs/demo"
mkdir -p .sstack/steps/dmm "$run"
printf 'after = "implement"\non_fail = "implement"\n' > .sstack/steps/dmm/step.toml
printf '#!/bin/sh\nprintf "migration check ok\\n"\n' > .sstack/steps/dmm/run.sh
chmod +x .sstack/steps/dmm/run.sh
sstack-workflow run dmm --run "$run"
```

`show --json` prints `chain`, and `steps.<name>` with `kind`, `role`, `gate`,
`on_fail`, `max_loops`, `max_agents`, `min_score`, `run`, `brief` and `source` — the
layer each key came from. That is the whole resolved shape, so check it before you
assume a value. Without `--json`, `show` prints the same chain with each step's
values, one step at a time.

## Change or disable a step

A repo that wants a stricter review and no separate plan step:

```sh
mkdir -p .sstack/steps/review .sstack/steps/plan
printf 'min_score = 7\n' > .sstack/steps/review/step.toml
printf 'enabled = false\n' > .sstack/steps/plan/step.toml
sstack-workflow show --json | python3 -c 'import json, sys; d = json.load(sys.stdin); s = d["steps"]["review"]; print("chain:", " ".join(d["chain"])); print("review min_score:", s["min_score"], "from", s["source"]["min_score"])'
```

```text
# expect
chain: recon implement gate review pr
review min_score: 7 from repo
```

Only `min_score` moved: `role` and `on_fail` still say `home` in `source`.
Disabling a step is the same shape — `enabled = false` in any layer's
`steps/<name>/step.toml` — and a `local/` file can turn off what the repo committed.

## Record each step

`work` records each step as it finishes and follows what the tracker prints:

- role or inline step: `sstack-workflow done <step> --run <run>`; a role step that
  routes to a member must have been dispatched first (see below)
- command step: `sstack-workflow run <step> --run <run>` — executed from the repo
  root with `SSTACK_RUN`, `SSTACK_ROOT` and `SSTACK_HOME` set
- `review`: `sstack-workflow done review --run <run> --findings <run>/review/findings.json`

```sh
run="$PWD/.sstack/runs/demo"
mkdir -p "$run"
sstack-workflow done plan --run "$run" # exit 1
sstack-workflow done plan --run "$run" --no-dispatch "demo"
```

The first call is refused: on the defaults `plan` routes to a member, and this run never
dispatched it. The refusal ends with the command to run. `--no-dispatch "<reason>"`
records the step anyway and writes `plan: no dispatch (demo)` to `progress.md`, so
skipping is visible. The second call prints three lines: `GATE: wait for the user's yes`,
`next: implement`, then a `do:` line. The other lines:

- `next: <step>` — where the chain goes next; `next: done` at the last step.
- `do: …` — how to do that step: its `sstack-dispatch <role> --step <step> …` command,
  `sstack-workflow run <step> --run <run>` for a command step, or "in this session" for
  an inline or local one.
- `GATE: wait for the user's yes` — after a step with `gate = true`. The next step
  starts on the user's yes.
- `STOP: ask user` with exit 2 — the step failed `max_loops` times, or failed with
  no `on_fail`. Nothing continues; ask the user.

`done` also releases this run's write-lock holder when it records the step that
dispatched an implement, so the next implement into the same checkout is allowed.

### The dispatch check

`done <step>` (a pass; `--fail` is never refused) exits 1 and records nothing when the
step is a role step that routes to a member and this run recorded no dispatch for it.
Routed means `max_agents` above 0 and a role that picks a member: not `local`, not
`[dispatch] via = "local"`. Command and inline steps are never checked. A recorded
dispatch is one `sstack-dispatch --step <step>` that reached `record` (under the run
folder, or in this checkout's `.sstack/runs/` when the run folder lives in another
checkout), or a local `implement` holding the write lock. A payload that was printed
but never carried out does not count.

## Review scores

The review step has `min_score`. The orchestrator writes
`<run>/review/findings.json` and records the step with that file; the code
recomputes every score after the findings are verified:

```json
[{"reviewer": "claude/opus", "score": 8,
  "findings": [{"severity": "Nit", "verified": true, "file": "lib/x.py", "where": "42"}]}]
```

- A verified `Important` caps that reviewer at 6.
- A reviewer whose `Important`s were all unverified is raised to at least 7 (10 when
  nothing verified is left).
- The final score is the lowest across reviewers.
- The step fails when the final score is below `min_score`, or when any verified
  `Important` remains. A failure routes to `on_fail` (built in: `implement`).

```sh
run="$PWD/.sstack/runs/demo"
mkdir -p "$run/review"
printf '[{"reviewer": "claude/opus", "score": 8, "findings": [{"severity": "Nit", "verified": true}]}]\n' \
  > "$run/review/findings.json"
sstack-workflow done review --run "$run" --findings "$run/review/findings.json" --no-dispatch "demo"
```

That one passes (`8` ≥ `min_score` 5, nothing `Important`), prints
`GATE: wait for the user's yes` then `next: pr`, and stores `"score": 8` on the
step in `workflow.json`, with `"patch"`: a sha256 fingerprint of the change it reviewed, which
[`sstack-gate --merge`](overnight.md) checks against the PR.

## A role step of your own

A custom step with `brief.md` and `role` is a role step: same brief every time,
scored by the same reviewers. Use it when a change needs one more opinion, not more
work — `role = "review"` with a narrower lens, or `role = "investigate"` for a
second opinion on a diagnosis.

```sh
mkdir -p .sstack/steps/dmm
printf 'after = "review"\nrole = "review"\n' > .sstack/steps/dmm/step.toml
printf 'Grade only the data-model change; ignore wording.\n' > .sstack/steps/dmm/brief.md
sstack-workflow show --json | python3 -c 'import json, sys; d = json.load(sys.stdin); s = d["steps"]["dmm"]; print("chain:", " ".join(d["chain"])); print("dmm:", s["kind"], s["role"], s["brief"])'
```

```text
# expect
chain: recon plan implement gate review dmm pr
dmm: role review <repo>/.sstack/steps/dmm/brief.md
```

`work` dispatches it by step name, so the role, the brief and the `max_agents` cap
come from the folder; nothing in the skill has to know it exists. A repo brief
beside a home-layer one wins whole.

## Where a run's state lives

`<run>/workflow.json` holds the chain's progress:

```json
{"current": "review",
 "steps": {"plan": {"status": "pass", "loops": 0, "score": null},
           "review": {"status": "running", "loops": 1, "score": 8}}}
```

Each `done` or `run` mirrors one line into `<run>/progress.md`, which is what
`sstack-doctor --prune-runs` and a resumed session read. `sstack-workflow status --run <run>`
prints the current step and each recorded step's status and loops, without changing
anything.

## How to change this

- Contract: [docs/spec/workflow.md](../spec/workflow.md) (steps, `workflow.json`, the CLI). The folder
  layout and merge rule are in [docs/spec/config.md](../spec/config.md).
- Built-in steps: the template `defaults/steps/<name>/step.toml` (plus `gate/run.sh`).
- Code: `lib/sstack_workflow.py` resolves and records; `bin/sstack-workflow` is the
  entry point. `lib/sstack_config.py` (`steps()`, `layers()`, `source()`) reads the
  folders.
- A new step needs no code: add its folder in `defaults/steps/` only when it ships
  to everyone, and say what it does in
  [skills/work/steps.md](../../skills/work/steps.md).
- Tests: `python3 -m unittest discover -s tests -p test_workflow.py`,
  `python3 -m unittest discover -s tests -p test_doctor.py`, then
  `python3 -m unittest discover -s tests -p test_docs.py`.
