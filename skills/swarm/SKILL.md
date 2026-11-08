---
name: swarm
description: Fan one question out to N independent children (role scout, or another role) through sstack-dispatch, then aggregate their PASS/ISSUES/BLOCKED reports into one result. Use for coverage sweeps ("check every service for X"), races (same brief, several models), or recon that needs many sources. Not for edits to a shared working tree.
---

# swarm

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.

Open a todo list with four items: Frame, Fan out, Aggregate, Report.

## Frame

1. State the **done predicate** (what answer ends the swarm) and what each child
   must return.
2. Choose the shape:
   - **partition** — split the space into disjoint slices (one service, one
     directory, one question each);
   - **race** — identical briefs to several harness/model pairs; declare the
     selection rule up front: `first pass`, `rank all` or `best-of`.
3. Size it: as few children as cover the space. Fewer than about five sources →
   don't swarm; read them here.
4. Children are read-only (role `scout` or `investigate`) and return everything in
   their report; dispatch captures it. Work that must write isn't a swarm: route it
   through `implement` in its own worktree (principle
   separate-before-serializing-shared-state).
5. When children check commits or measure, each brief names the exact SHAs and the
   method (sample count, order), and the child records both.

## Fan out

For each slice, write a standalone brief from `<sstack>/skills/work/brief-template.md` (goal,
the exact slice, how to verify, the report contract) to
`.sstack/runs/<run-id>/scout-<n>.brief.md`, then start all children together:

```sh
RUN=<run-id>; TASK="<short task name>"; pids=()
for n in 1 2 3; do
  <sstack>/bin/sstack-dispatch scout --brief .sstack/runs/$RUN/scout-$n.brief.md \
    --report .sstack/runs/$RUN/scout-$n.report.md --title "$TASK scout $n" &
  pids+=($!)
done
for i in "${!pids[@]}"; do wait "${pids[$i]}"; echo "scout-$((i+1)) exit=$?"; done
```

Handle each child by its own exit: 0 → read the report; 3 → that slice is local;
1/2 → a gap to report, never a silent pass.

Exit 3 (`local`) → the role isn't routed: either run the slices here one by one,
or use the harness's native subagents (see harness notes) with the same briefs.
A race across models: put the arms in a `[role.review]`-style `panel` in
`.sstack/config.local.toml` on `scout`, `investigate` or `review`. Don't invent
role names for arms: only those three (and `plan`) run read-only.

Each child's report ends `PASS`, `ISSUES` or `BLOCKED` with evidence. A child that
can prove a defect lists every one it can prove, not only the first.

## Aggregate

- Read every report. A report without the evidence its brief asked for (commands
  and output, SHAs, method) → respawn that child once with the gap named. A second
  miss → record a **gap**. A gap never counts as a pass.
- Coverage: every slice needs a result. Race: apply the rule you declared.
- Spot-check the decisive claims yourself (re-run one command per finding that
  matters). Don't paste raw dumps.

## Report

One consolidated reply: a table (slice → status → one-line finding), issue
one-liners with evidence, gaps and dropouts, and the race rule if used.

---
Adapted from pstack `swarm` (michael-denyer/pstack-claude @ 91ab921, MIT).
