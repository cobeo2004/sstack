---
name: overnight
description: Run the runs or decisions tickets you list at bedtime through work while you sleep - gates answered for this session only, PRs merged only where the [overnight] policy allows, and a report in the morning. Use for "run my listed work while I sleep", "get these done overnight", "finish them while I sleep".
---

# overnight

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.

`overnight <run-dir|decisions.md>...`. One bedtime, several runs, one at a time in the order given.
[work](../work/SKILL.md) does each run; this skill answers its gates, merges only what
`sstack-gate --merge` allows, and writes the morning report.

## Start

1. Create the session dir `.sstack/runs/overnight-<YYYYmmdd-HHMM>/`. The report goes there.
2. Resolve the list, in the order given:
   - a run dir → that dir;
   - a confirmed [grill](../grill/SKILL.md) `decisions.md` → the run dir beside it;
   - nothing → the current run: `sstack-workflow status --run <run>` prints `at: <step>`, and a
     `progress.md` whose last `done:` line is missing is unfinished. Newest unfinished wins.
   Never pick work from a backlog or an issue tracker (Q2). Say the list back in one line.
3. Read the policy with `sstack-config show config` (layers lowest first, a later key wins).
   Keys: `merge`, `method`, `merge_min_score`, `max_diff_lines`, `never_merge`,
   `merge_with_assumptions`, `on_question`, `on_stuck`, `stop_at` ([config spec](../../docs/spec/config.md)).
   `sstack-gate --merge` re-reads it from the base branch, so its verdict beats your reading.
4. `stop_at` (`""`, or local `HH:MM`): fix one deadline now, the next time that clock time comes
   round (today if still ahead, else tomorrow), so 23:00 with `07:00` means 07:00 tomorrow. Before
   each run compare full timestamps (`date +%s`); at or past it, start no new run. The current one
   finishes or parks; the rest stay unstarted and are reported (R13).

## Loop

For each run, in order:

1. **Fresh base.** A run with no commits yet: `git fetch`, then cut its branch from the freshly
   fetched default branch. A run already under way keeps its own branch and checkout. Never branch
   from another run's branch: no stacked PRs (R9).
2. **Continue, don't restart.** `sstack-workflow status --run <run>`, then that dir's `progress.md`,
   `plan.md` and latest reports. Run `work` from the run dir: it resumes at the first unfinished
   step. Say which step that is; don't redo finished ones.
3. **Gates are yes, this session only.** Every `GATE: wait for the user's yes` in a listed run —
   `recon`, `plan`, `review` and the locked `pr` one — is answered yes: commit, normal push, open
   the PR. Say "yes" in one line and record it. Nothing widens this: no config key, no other run,
   and it ends with this session (R2).
4. **Questions.** `on_question = "decide"`: where `work` would ask, pick the recommended answer,
   append `<question> → <choice> (<why>)` to `<run>/assumptions.md`, carry on. `"park"` stops the
   run and moves to the next one (R10). `assumptions.md` goes in the PR body and the report.
5. **Stuck.** `on_stuck = "draft"`: on `STOP: ask user` (loop cap) make one more attempt on the
   strongest tier. If that fails, commit the WIP and open a draft PR carrying the failure output
   and `assumptions.md`; a draft is never merged. `"park"` leaves the run stopped (R11).
6. **CI red.** One fix attempt through implement → gate → review, capped by `loop_guard`, pushed
   with a normal push. Still red → the PR stays open and the reason goes in the report (R8).

After opening a PR, don't wait for CI. Record the URL and move on (R7).

## After a PR

`work`'s `pr` step gates before the commit, so that verdict is `(dirty)`. Once the commit is pushed,
run `<sstack>/bin/sstack-gate --run <run> --pr` again on the clean tree, then
`<sstack>/bin/sstack-gate --merge <pr> --run <run>`. `--merge` holds unless the latest `--pr` verdict
was taken on the PR's head, and unless the change is the one the review step recorded: a fix after
review means review again (R5).

- Exit 0, first line `MERGE` → `gh pr merge <pr> --<method> --delete-branch`, `method` from
  `[overnight]`. Record "merged <url>". Never into a branch but the default one (R6).
- Exit 1, first line `HOLD: <reasons>` → leave it open and record the reasons. If they include
  `ci: failed`, make the one fix attempt from Loop step 6 whatever the other reasons are (merging
  is a separate question), then gate, review and `--merge` again. `ci: pending` waits for the next
  re-check. Nothing else in a `HOLD` is fixed overnight.
- Exit 2 → `gh` or the `repos.txt` trust check failed: record it and stop merging for the session.

Between runs, and once at the end, run `--merge` again for every PR this session opened and merge
the ones that now pass. A PR now at `ci: failed` gets its one fix attempt then, if it has not had it. A PR still pending at the end stays open, with its `HOLD` reasons in the
report.

## Never

Hard-coded, whatever the config says. A run that needs one is parked: record it and move on.

- Force-push, amend or otherwise rewrite pushed history.
- Merge into anything except the repo's default branch.
- Edit or delete a file matching `protected`, or `.sstack/project.toml`.
- `sstack-config migrate`, a release, or a deploy.
- Edit the user's sstack config: anything under `~/.sstack/`, `.sstack/` or `.sstack/local/`
  except `.sstack/runs/`, including `[overnight]` itself. The `pr` gate stays locked.

Human review comments are out of scope overnight: leave them for the morning.

## Report

Write `.sstack/runs/overnight-<stamp>/report.md`: one line per listed run, then the assumptions.

```text
# overnight YYYYmmdd-HHMM
- <run>: merged <pr url>
- <run>: PR open <pr url> - HOLD: <reasons>
- <run>: draft <pr url> - <why>
- <run>: parked at <step> - <reason>
- <run>: not started - stop_at <HH:MM>
## Assumptions
- <run>: <question> → <choice> (<why>)
```

Send a push notification that the report is ready, if the harness can (R14).

## Morning

The report is the handoff. A parked run resumes with plain `work` from that run's dir: it reads
`progress.md`, `plan.md` and `sstack-workflow status`, and starts at the first unfinished step.
There is no overnight-specific resume (R15). An open PR re-checks with `--merge`, or goes to
[babysit](../babysit/SKILL.md).
