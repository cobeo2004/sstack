---
name: swarm
description: Fan one question out to N independent children (role scout, or another role) through dispatch, then aggregate their PASS/ISSUES/BLOCKED reports into one result. Use for coverage sweeps ("check every service for X"), races (same brief, several models), or recon that needs many sources. Not for edits to a shared working tree.
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
`.sstack/runs/<run-id>/scout-<n>.brief.md`. Dispatch `scout` for every slice and
start all of them before collecting any report, following
[sstack § Delegation](../sstack/SKILL.md#delegation).

Keep one report per slice and member: `scout-<n>.report.md` for a single member;
dispatch names each member report
(`scout-<n>.report.<harness>-<model>.md`), so no member overwrites another.

A `panel` on `scout` runs every member for every slice: N slices × M members
children. For a partition, use a single-member scout; keep panels for races.

Exit `3` makes that slice local. Exit `1`/`2` is a gap to report, never a
silent pass. Run local slices here one by one with the same briefs.

A race across models: put the arms in a `panel` in
`.sstack/local/roles/<role>.toml` for `scout`, `investigate` or `review`.
Don't invent role names for arms: only those three (and `plan`) run read-only.

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
