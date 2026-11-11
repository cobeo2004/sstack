---
name: work
description: Run any engineering task (feature, bug fix, refactor, perf, multi-phase) through the repo's resolved workflow steps - recon and report, plan with an answer key, implement (local or routed through dispatch), test/fix with review, PR on the user's yes. Ticket ID optional. Use for "work this", "work UNI-142", "fix this bug", "build X", "phase 0 this", or when the sstack router picks a playbook.
---

# work

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.

`work [TICKET-ID] <task>`. The workflow is config, not prose: `steps/<name>/step.toml`
folders resolve per key across the config layers, so a repo or a user can add,
disable, reorder or re-gate a step. Read the chain; never assume it.

## Start

1. Create the run directory: `.sstack/runs/<run-id>/` with `run-id` =
   `<ticket-or-slug>-<YYYYmmdd-HHMM>`. Everything that must survive a compaction or
   a new session goes there: `recon.md`, `plan.md`, `answer-key.md`, `protected/`,
   briefs, reports, `progress.md` (one line per finished step). Task scratch stays in
   that folder, never a new top-level folder under `.sstack/runs/`: a dispatch with
   a `--report` there nests under it. If `grill` handed over a run directory, or
   `ls .sstack/runs/*/decisions.md` shows one for this task, use it instead:
   `decisions.md` is the ticket and everything else goes beside it.
2. Run `<sstack>/bin/sstack-workflow show`. That output is the chain: step names in
   order, each with its role or command, gate, `on_fail`, loop cap, agent cap and
   (review) `min_score`. Custom, disabled and reordered steps are already applied.
   Add `--json` when you need the fields by name.
3. Open a todo list in chain order, then let [steps.md](steps.md) drive it. A repo
   that changed a step's `gate`, `max_agents` or `min_score` changed the work: the
   chain, not this file, is the truth.
4. Resume: if the user says "continue" or a run dir for this task exists, read its
   `progress.md`, `plan.md` and latest reports, `sstack-workflow status --run <run>`
   for the current step and loop, and check `git status` / `git log` against them.
   Pick up at the first unfinished step. Trust the files and git over memory.

## Follow the chain

[steps.md](steps.md) says what each built-in step does, one section per step name.
After every step, record it and read what it prints:

- `sstack-workflow done <step> --run <run>` for a role or inline step. Review is
  `done review --run <run> --findings <run>/review/findings.json`.
- `sstack-workflow run <step> --run <run>` for a command step: it executes the
  step's `run.sh` from the repo root and records pass or fail.
- `next: <step>` → go there, by running the `do: …` line printed after it. `next: done`
  → the chain is finished.
- `done` refuses (exit 1) a routed role step that nobody dispatched, and prints the
  command: run it. Skip only with `--no-dispatch "<reason>"`.
- `GATE: wait for the user's yes` → stop, report, and wait. A gate belongs to this
  session; a child never approves one.
- exit 2 with `STOP: ask user` → the step hit its loop cap, or failed with no
  `on_fail`. Stop and ask. Don't start a third attempt on the same failure.

A step that is not in the chain is deliberately off: don't run it anyway. A step
`steps.md` does not describe came from a config layer: read the `kind` that `show`
printed — `command` → `run`; `role` → dispatch with `--step`; `inline` → do it here.

## Pick the playbook

The `sstack` router picks the playbook: [feature](playbooks/feature.md),
[bug-fix](playbooks/bug-fix.md), [refactor](playbooks/refactor.md),
[perf](playbooks/perf.md), [multi-phase](playbooks/multi-phase.md). Copy its steps
into the todo list verbatim; a skipped one stays, marked `skip: <reason>`. A
playbook shapes the work inside the steps: which surfaces to check, what the answer
key must pin, when to stop early.

## Always

- Every check is written and run per [testing.md](testing.md); every step and check
  cites the `R#` it serves per [traceability.md](traceability.md).
- A routed child never approves its own gate. A dispatch exit `1`/`2` stops at the
  next gate; don't quietly redo it here.
- Irreversible or outward-facing actions (commit, push, PR, deploy, delete data)
  wait for the user's explicit yes, even mid-chain.
- Verification gate from `sstack` before every claim; at the end, run `reflect` if
  the user corrected you or you hit a dead end.

## Repo playbook overrides

A repo may add `.sstack/playbooks/<name>.md` with frontmatter `extends: <bundled
playbook>` (or empty for a standalone playbook) and `when: <one sentence>`. Its
body is a list of changes, each starting `**After**`, `**Before**`, `**Replace**`
or `**In**` followed by a quoted run of the bundled step's own words. Copy the
bundled steps first, then apply each change at the step its quote names. A quote
that matches no step → tell the user; don't guess where it belongs.

---
Adapted from the user's phased-work skill, pstack playbooks (michael-denyer/pstack-claude
@ 91ab921, MIT) and orbyn's answer key + loop guard (orbyn-dev/orbyn-fullstack-skills
@ 185e5a5, MIT).
