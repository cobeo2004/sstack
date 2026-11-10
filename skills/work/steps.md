# Steps

`work` follows the chain `<sstack>/bin/sstack-workflow show` prints. This file holds
what each built-in step does. `show` names the order, each step's `role`, `gate`,
`on_fail`, `max_loops`, `max_agents` and `min_score`, and the layer each key came
from; `show --json` gives the same as fields. Steps are folders
(`steps/<name>/step.toml`, plus `brief.md` or `run.sh`), so a user or repo may add,
disable or reorder them: [the workflow guide](../../docs/guide/workflow.md).

Read the step's own row before doing it: a repo that set `gate = false` or
`max_agents = 2` changes what happens next, and `show` is the only place that says so.

Record every step, then do what it prints:

| step kind | record with |
|---|---|
| role step, inline step | `sstack-workflow done <step> --run <run>` |
| command step (`run.sh`) | `sstack-workflow run <step> --run <run>` — runs it from the repo root |
| `review` | `sstack-workflow done review --run <run> --findings <run>/review/findings.json` |

- `next: <step>` — go there.
- `GATE: wait for the user's yes` — stop, report, and wait. The next step starts on
  the user's yes.
- exit 2 with `STOP: ask user` — the step failed `max_loops` times, or failed with
  no `on_fail`. Stop and ask. Never loop past it.

## recon

1. Check the checkout: `<sstack>/bin/sstack-worktree` (linked or primary, branch,
   behind/ahead of base, dirty, gitignored files and dirs the primary has that this
   tree lacks). Missing env files → `sstack-worktree copy` copies only what the
   primary's `.worktreeinclude` lists; anything else missing goes in SYSTEM STATE,
   never copied by hand. Missing dirs (`node_modules/`) → reinstall, don't copy.
   Worktrees still share databases, ports and services: note any this task touches.
2. Sync with the base branch (fetch; note how far behind you are). Read the ticket
   if there is one (or `decisions.md` if `grill` produced this run), the house rules
   (`AGENTS.md`/`CLAUDE.md`), `.sstack/product.md`, the docs it links, and the ADRs
   and glossary covering this area: [traceability.md](traceability.md).
3. No falsifiable definition of done and no `decisions.md` → run `grill` first.
   Otherwise clarify one question at a time, only where no command can answer;
   where running something would answer it, run it or build a throwaway prototype.
4. Route the recon reading: dispatch `investigate` with `--step recon` and the recon
   questions as the brief, following [sstack § Delegation](../sstack/SKILL.md#delegation).
   Many independent sources → `swarm` with role `scout` instead. Use `code-graph`
   (`detect-changes` / impact) to find what the change reaches. Read every report,
   stage variants' `<report>-<name>.md` too, and check their file pointers yourself;
   this gate stays here.
5. Write `recon.md` with exactly these headings, then **stop and report it**:
   - **SYSTEM STATE** — what exists today, with file paths.
   - **THE PATTERN / CAUSE / DIFF** — the pattern to follow, the root cause (bug),
     or the diff in behaviour wanted.
   - **THE PLAN SHAPE** — the ordered changes, roughly.
   - **THE TEST STRATEGY** — what proves it works: each check's surface (code,
     browser, mobile), how it's written and run, per [testing.md](testing.md).
   - **RISKS** — what could break, what's shared.
   - **WHAT I COULD NOT VERIFY** — say it plainly.

Then `sstack-workflow done recon --run <run>`. On `GATE: wait for the user's yes`,
the user reads the report: don't plan until they respond. A repo that set
`gate = false` on `recon` means the report goes in the reply and `work` continues.

## plan

1. Write `plan.md`: ordered, bite-sized steps. Each names the `R#` it serves
   ([traceability.md](traceability.md)), exact files, the change, the check that
   proves that step, and its **kind** (`frontend`, `backend`, `mobile`, `security`,
   `complex`, `mechanical`, `docs`, or a config hint; see
   [sstack § Delegation](../sstack/SKILL.md#delegation)). The kind picks the model,
   so the user approves the routing at this gate. One step = one verifiable unit. A
   step that spans frontend and backend is either tagged `complex` or split in two.
2. Write the **answer key** (`answer-key.md`) before any implementation, so
   correctness is defined by something the implementer can't change:
   - the success checks, each tagged `code:`, `browser:` or `mobile:` and written
     per [testing.md](testing.md): a command that exits 0 only when the outcome is
     right, or a scripted browser/device check with its expected states;
   - the expected end state (files, behaviour the commands observe);
   - protected paths: the tests/fixtures that define correctness. Copy each into
     `protected/`; write `protected/SHA256SUMS` (`shasum -a 256`, repo-relative
     paths) and `protected/mode` (`restore`, or `strict` when editing the test is
     forbidden); note the base commit in `progress.md`.

   The implementer's brief names the outcome, not the key.
3. Role `plan` may draft the plan if the step's `role` is routed (merge any variant
   reports); the gate stays here.

Then `sstack-workflow done plan --run <run>`. At `GATE: wait for the user's yes`,
the harness's plan approval (see harness notes) or an explicit "yes" in chat where
there is none, and no requirement left without a check, is the gate. Nothing gets
implemented before it.

## implement

- Per step (or group of steps of one kind): dispatch `implement` with `--step
  implement` and a brief from [brief-template.md](brief-template.md) containing the
  approved plan, plus the step's files and kind. `--step` takes the role, the brief
  and the concurrency cap from the step folder. Follow
  [sstack § Delegation](../sstack/SKILL.md#delegation); without `--hint` the kind is
  detected from `--files`.
- A failed child is retried once, one tier up, by the dispatcher itself
  (`rules.auto_escalate`); the stderr line and `index.jsonl` say so. Check the
  escalated child's diff like any other.
- Exit 3 (`local`) → implement here, step by step, checking each step. An exit 3
  from a write role holds the checkout's write lock until `done implement`, so
  record the step before dispatching another implement.
- `exit 5` (`BUSY: <run> <files>; nothing started`) → another run holds this
  checkout's write lock and nothing started. Say you are waiting on that holder,
  wait for it to record its step or finish, then dispatch again. Never kill it or
  work around it in the same tree.
- One implementer edits the tree at a time. `max_agents > 1` runs a group in
  parallel **only** when the ADE isolates children in their own checkouts and the
  steps' files are disjoint; headless, local, or overlapping files fall back to 1
  with a printed reason. Bring each child's diff back one at a time and `run gate`
  after each, so a failing child is caught before the next lands.
- No commits, no PR from a child.
- Read the report **and** the change itself before moving on: `git diff`, or
  `git -C <child worktree> diff` in its own checkout
  ([sstack § Delegation](../sstack/SKILL.md#delegation)); bring it here before the
  gate step.

Then `sstack-workflow done implement --run <run>`.

## gate

A command step: `sstack-workflow run gate --run <run>` executes
`defaults/steps/gate/run.sh`, which is `<sstack>/bin/sstack-gate --run "$SSTACK_RUN"`
from the repo root. Do this before it:

1. Restore `protected/` in `restore` mode.
2. Run the answer key and save before/after media per [testing.md](testing.md).

FAIL → the step's `on_fail` (built in: `implement`) with `<run>/gate/<n>.md`, and no
review on a failing gate. The same failure twice → change approach once and say how;
the loop cap stops the attempt after that (`STOP: ask user`).

## review

1. Run `review` on the diff with `--step review` (role `review`, ideally a different
   model family from the implementer). Its result merges variant reports; the
   reviewer's brief asks for a 1–10 score on the anchored rubric.
2. Re-check every finding against the current head: reproduce it, keep it only if it
   still breaks the intent, and drop or reclassify what the current code already
   handles. Record each finding's `verified` flag — `true` only for one you
   reproduced yourself this pass.
3. Write `<run>/review/findings.json`, one row per reviewer:

   ```json
   [{"reviewer": "codex/gpt-6.1-sol", "score": 8,
     "findings": [{"title": "…", "severity": "Important", "verified": true,
                   "file": "lib/x.py", "where": "42", "evidence": "command + output"}]}]
   ```

4. `sstack-workflow done review --run <run> --findings <run>/review/findings.json`.
   It recomputes each score after dropping unreproduced findings: a verified
   Important caps that reviewer at 6, a reviewer whose Importants were all
   unverified is raised to 7 (10 when nothing verified remains), and the final score
   is the lowest across reviewers. It fails the step when the final score is below
   the step's `min_score` (default 5) or any verified Important remains.

A fail routes to the step's `on_fail` (built in: `implement`): fix, then re-review.
Pass prints `GATE: wait for the user's yes`: report commands + results, findings,
per-reviewer and final score, and nits listed. Nothing continues until the user says
yes.

## pr

1. `unslop` the diff and the PR text. Use the repo's PR template if it has one.
2. Rebase/merge base; re-run the answer key and `<sstack>/bin/sstack-gate --run
   <run> --pr` on the result; either fails → back to the implement or review step.
   Show any `MEDIA WAIVED: <reason>` line at the gate.
3. **The gate is always on** (`pr` cannot be disabled and its `gate` cannot be set
   false): the user's explicit yes before commit, push or PR, and before publishing
   media. Then push, open the PR, and run
   `<sstack>/bin/sstack-pr-media <pr> <run>/media/* --edit-body` right after opening,
   so the Before | After table lands in the PR description per [testing.md](testing.md).
   PR comments are only for add-ons, never the main evidence.
4. `sstack-workflow done pr --run <run>` prints `next: done`. When the PR opens (or
   the user stops the task), append `done: <PR url | reason>` as the last line of the
   run's `progress.md`; `--prune-runs` reads it.

Then hand off to `babysit`.

## A step this file does not describe

`show` lists a step whose name is not above → it came from a config layer, so read
the line it printed:

- `kind: command` (it has a `run.sh`) → `sstack-workflow run <step> --run <run>`
  records it; exit 0 passes, anything else fails and routes to its `on_fail`.
- `kind: role` → dispatch it with `--step <step>`: the step's `role` picks the
  member and its `brief.md` is the brief. Read the report and the change here, then
  record it with `done`.
- `kind: inline` with no `run.sh` → do it here, then record it with `done`.

Never skip a step you cannot classify: ask the user, or `sstack-workflow show` again
with `--json` and read its fields.
