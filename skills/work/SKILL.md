---
name: work
description: Run any engineering task (feature, bug fix, refactor, perf, multi-phase) through gated phases - recon and report, plan with an answer key, implement (local or routed via sstack-dispatch), test/fix with review, PR on the user's yes. Ticket ID optional. Use for "work this", "work UNI-142", "fix this bug", "build X", "phase 0 this", or when the sstack router picks a playbook.
---

# work

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.

`work [TICKET-ID] <task>`. The `sstack` router picks the playbook:
[feature](playbooks/feature.md), [bug-fix](playbooks/bug-fix.md),
[refactor](playbooks/refactor.md), [perf](playbooks/perf.md),
[multi-phase](playbooks/multi-phase.md). Copy the playbook's steps into the todo
list verbatim; skipped steps stay, marked `skip: <reason>`.

Create a run directory first: `.sstack/runs/<run-id>/` with `run-id` =
`<ticket-or-slug>-<YYYYmmdd-HHMM>`. Everything that must survive a compaction or a
new session goes there: `recon.md`, `plan.md`, `answer-key.md`, `protected/`,
briefs, reports, `progress.md` (one line per finished step). If `grill` handed
over a run directory, or `ls .sstack/runs/*/decisions.md` shows one for this task,
use it instead: `decisions.md` is the ticket and everything else goes beside it.

**Resume:** if the user says "continue" or a run dir for this task exists, read
its `progress.md`, `plan.md` and latest reports, check `git status` / `git log`
against them, and pick up at the first unfinished step. Trust the files and git
over memory.

## Phase 0 — Recon → gate

1. Check the checkout: `<sstack>/bin/sstack-worktree` (linked or primary, branch,
   behind/ahead of base, dirty, gitignored files and dirs the primary has that this
   tree lacks). Missing env files → `sstack-worktree copy` copies only what the
   primary's `.worktreeinclude` lists; anything else missing goes in SYSTEM STATE,
   never copied by hand. Missing dirs (`node_modules/`) → reinstall, don't copy.
   Worktrees still share databases, ports and services: note any this task touches.
2. Sync with the base branch (fetch; note how far behind you are). Read the ticket
   if there is one (or `decisions.md` if `grill` produced this run), the house rules
   (`AGENTS.md`/`CLAUDE.md`), `.sstack/product.md`, and the docs it links that
   matter here.
3. No falsifiable definition of done and no `decisions.md` → run `grill` first.
   Otherwise clarify: one question at a time, only for things no command can
   answer. If running something would answer it (behaviour, output, timing), run
   it or build a throwaway prototype instead of asking.
4. Fan out only for many-source questions: `swarm` with role `scout`. Use
   `code-graph` (`detect-changes` / impact) to find what the change reaches.
5. Write `recon.md` with exactly these headings, then **stop and report it**:
   - **SYSTEM STATE** — what exists today, with file paths.
   - **THE PATTERN / CAUSE / DIFF** — the pattern to follow, the root cause (bug),
     or the diff in behaviour wanted.
   - **THE PLAN SHAPE** — the ordered changes, roughly.
   - **THE TEST STRATEGY** — what proves it works: each check's surface (code,
     browser, mobile), how it's written and run, per [testing.md](testing.md).
   - **RISKS** — what could break, what's shared.
   - **WHAT I COULD NOT VERIFY** — say it plainly.

**Gate 0:** the user reads the report. Don't plan until they respond.

## Phase 1 — Plan → gate

1. Write `plan.md`: ordered, bite-sized steps. Each names exact files, the change,
   the check that proves that step, and its **kind** (`frontend`, `backend`,
   `mobile`, `security`, `complex`, `mechanical`, `docs`, or a config hint; see
   `<sstack>/bin/sstack-dispatch routes`). The kind picks the model, so the user
   approves the routing at Gate 1. One step = one verifiable unit. A step that
   spans frontend and backend is either tagged `complex` or split in two.
2. Write the **answer key** (`answer-key.md`) before any implementation, so
   correctness is defined by something the implementer can't change:
   - the success checks, each tagged `code:`, `browser:` or `mobile:` and written
     per [testing.md](testing.md): a command that exits 0 only when the outcome is
     right, or a scripted browser/device check with its expected states;
   - the expected end state (files, behaviour the commands observe);
   - protected paths: the tests/fixtures that define correctness. Copy each into
     `protected/` and record its `sha256` (`shasum -a 256 <file>`) and the base
     commit. Default mode `restore`; `strict` only when editing the test is itself
     forbidden.
   The implementer's brief names the outcome, not the key.
3. Role `plan` may draft the plan if routed; the gate stays here.

**Gate 1:** the harness's plan approval (see harness notes), or an explicit "yes"
in chat where there is none. Nothing gets implemented before it.

## Phase 2 — Implement

- Per step (or group of steps of one kind): `<sstack>/bin/sstack-dispatch implement
  --brief <run>/implement-<n>.brief.md --report <run>/implement-<n>.report.md
  --title "<ticket> implement" --hint <kind> --files <the step's files>`, brief from
  [brief-template.md](brief-template.md) containing the approved plan. Without
  `--hint` the kind is detected from `--files`.
- A failed child is retried once, one tier up, by the dispatcher itself
  (`rules.auto_escalate`); the stderr line and `index.jsonl` say so. Check the
  escalated child's diff like any other.
- Exit 3 (`local`) → implement here, step by step, checking each step.
- One implementer edits the tree at a time. No commits, no PR from a child.
- Read the report **and** `git diff` yourself before moving on.

## Phase 3 — Test / fix with review → gate

1. Restore protected files from `protected/` and confirm their hashes, then run
   every answer-key check on its surface per [testing.md](testing.md) and read the
   output. For changes a user can see, save before/after media per testing.md
   (`<run>/media/`). A changed protected file is
   reported, never accepted silently.
2. Failures → back to Phase 2 with the failing commands and output added to the
   brief. **Loop guard** (`rules.loop_guard`, default 2): the same failure twice →
   change approach once and say how; if it fails again, stop and ask.
3. Run `review` on the diff (role `review`, ideally a different model family from
   the implementer). Re-check every finding yourself before acting on it.

**Gate 3:** all checks green **and** every review finding fixed or explicitly
agreed out of lane by the user. Report commands + results, findings + outcome.

## Phase 4 — PR → gate

1. `unslop` the diff and the PR text. Use the repo's PR template if it has one.
2. Rebase/merge the base branch and re-run the answer key on the result.
3. **Gate 4:** the user's explicit yes before commit, push or PR, and before
   publishing media. Then push, open the PR, publish the PR evidence per
   [testing.md](testing.md) (`<sstack>/bin/sstack-pr-media <pr> <run>/media/*`, then
   post its output with `gh pr comment`), and hand off to `babysit`.

## Always

- A routed child never approves its own gate. Dispatch exit 1/2 → stop at the next
  gate and tell the user; don't quietly redo it here.
- Verification gate from `sstack` before every claim.
- At the end, run `reflect` if the user corrected you or you hit a dead end.

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
