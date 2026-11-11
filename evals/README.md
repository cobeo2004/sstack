# evals

Behaviour evals for the `work` skill. Does a real agent follow the workflow and start the subagent
the config routes to, or does it do the step itself? Unit tests can't answer that, because they
never run a model. These do: each case is a real Claude Code run, graded on the tool calls it made.

```sh
evals/run.sh                                # every case, 3 runs each
evals/run.sh --case 'implement-*' --runs 5  # one glob; any `claude plugin eval` option passes through
evals/run.sh --model opus                   # the model you drive work with
```

Each run uses your Claude credential and costs real money, about $0.30 a run at the default
model. `run.sh` copies the checkout's tracked and new files to a temp dir and runs
`claude plugin eval` there. Local state (`.sstack/runs`, `.omc`, old results) never loads.
Results and every run's trace land in `evals/results/<stamp>/`, which git ignores.

## CI

`.github/workflows/evals.yml` runs static evals only. It calls no model and needs no secret. It
runs on PRs that touch `evals/`, `skills/`, `lib/`, `bin/` or `defaults/`, and on pushes to main.
Two things must hold:

- Every case's scaffold builds its fixture.
- The graders are re-scored against recorded real runs in `_fixture/traces/`. Those are the
  orchestrator's tool calls only, trimmed, with paths scrubbed. Each `<case>.pass.jsonl` comes
  from a run that followed the workflow, and it must pass every grader.
  `implement-shell-pi.skip.jsonl` is a run that skipped its dispatch with `--no-dispatch`, and it
  must fail `dispatched`, `no-skip`, `recorded` and `shell-child`.

A grader edit that stops catching the skip, or starts failing a good run, breaks CI. The paid
model runs stay local (`evals/run.sh`). When you add a case, record one run of it with
`evals/run.sh --case <name> --runs 1`. Trim its trace from `evals/results/<stamp>/traces/` into
`_fixture/traces/<name>.pass.jsonl`, keeping one JSON object with `name` and `input` per tool call.

## Cases

Every case runs in bare Claude Code, so `CLAUDECODE` is set and the `claude` harness's
`[session]` table is the dispatch path. `_fixture/setup.sh` builds the same state for each case:

- a synced sstack profile in the run's temp `HOME`;
- a one-file repo, either a plain checkout or a linked git worktree;
- a run folder already past the plan gate.

| Case | Layout | Routes to | Passes when the agent |
|---|---|---|---|
| `implement-agent-plain` | plain | claude/haiku | runs `sstack-dispatch implement --step implement`, then `Agent` with `isolation: worktree`, then `done` |
| `implement-agent-worktree` | worktree | claude/haiku | does the same from a linked worktree |
| `implement-shell-pi` | worktree | pi | runs the payload's backgrounded `Bash` `pi -p …` and no `Agent` |
| `review-agent` | plain | claude/sonnet | starts a read-only reviewer `Agent` (no isolation) from the review payload |
| `inline-local` | plain | `max_agents = 0` | (control) does the step itself and starts nothing |

Every case also fails if the agent passes `--no-dispatch` or writes `workflow.json` by hand. Those are the two shortcuts these evals exist to catch.

## Limits

- The eval harness can't create agent worktrees. An `Agent` call with `isolation: worktree` gets
  refused, and the right recovery is `sstack-dispatch … --via local` (exit 3), so `recorded`
  accepts either path.
- T3 isn't covered. Its `delegate_task` lives on T3's MCP server, which an eval can only mock
  when the plugin itself declares that server.
- Children often can't run inside the eval sandbox. Worktree isolation is unavailable, and a
  harness CLI installed under `/Users` (pi via bun, for one) is blocked. The cases grade the
  orchestrator: dispatch, the payload's call, then either `done`, or a failed `record` and a stop.
  A child that does the work successfully is not part of the grade.
- `tests/test_evals.py` runs each scaffold without a model, so a broken fixture fails the
  unit suite before it can waste an eval run.
