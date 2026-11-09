---
name: sstack
description: Entry point for any engineering request (build, fix, refactor, speed up, review, explain, set up a repo, diagram, "what went wrong") and for "/sstack". Picks the right sstack skill or playbook, loads repo context and accepted lessons, and enforces gates, verification and delegation rules. Use before starting engineering work.
---

# sstack

The router for the sstack skill stack. Read this first on any engineering task,
pick a route, then follow that skill.

`<sstack>` in every sstack skill means the sstack repo root: two levels up from
this file's resolved path (skills are symlinked; resolve the link, e.g.
`readlink -f` on this file). Tools live in `<sstack>/bin/`.

## Start of every task

1. Run `<sstack>/bin/sstack-dispatch ade`. It fails or returns no `name` → there is
   no ADE: use the harness note and say so once. Otherwise read its `note`: the
   active ADE's delegation, browser, device and capture procedure.
2. Read the repo's `AGENTS.md` and/or `CLAUDE.md`.
3. Read `.sstack/product.md` if it exists. In a linked worktree with none, read the
   primary checkout's (`git worktree list --porcelain`, first entry) — the same
   fallback config and repo lessons use. If neither has one and the task is more
   than a one-liner, say once that `setup` would create it, then carry on.
4. Load accepted lessons from both scopes and follow them:
   `<sstack>/bin/sstack-lessons list --status accepted --scope repo` and
   `... --scope global`. Repo scope in a linked worktree reads the primary's
   `.sstack/lessons.md` unless this checkout has its own.
5. Say back, in one or two sentences, the user's goal and the smallest change you
   expect to meet it. Don't wait for confirmation unless the evidence rules out
   what they asked for; then show it and stop.

## Route the request

| Request | Go to |
|---|---|
| Make a repo agent-ready, new or existing ("set up", "onboard this repo") | `setup` |
| Fuzzy idea, "brainstorm", "help me think this through" | `grill` (fuzzy opening), then `work` |
| Stress-test a plan or design, "grill me" | `grill` |
| "Prototype", "sketch it to decide" | `grill`; its prototype settles the question |
| New or changed behaviour | `work` → playbook `feature` |
| A defect to reproduce and fix ("bug", "broken", "regression") | `work` → `bug-fix` |
| "Just find the cause", "diagnose only" | `work` → `bug-fix`, diagnose-only exit |
| Behaviour-preserving restructure (rename, extract, dedupe, move) | `work` → `refactor` |
| Measured slowness | `work` → `perf` |
| Spans several phases or PRs, a migration | `work` → `multi-phase` |
| Review a diff or PR, "are we sure?" | `review` |
| PR status, CI red, review comments to handle | `babysit` |
| How does X work | `how` |
| Why is X this way, who decided | `why` |
| One question that needs many independent looks | `swarm` |
| Architecture / sequence / data-flow / state picture | `diagram` |
| Impact of a change, dependency graph, "what does this touch" | `code-graph` |
| Clean up a diff or prose before a PR | `unslop` |
| The user corrects you, you hit a dead end, or "remember this" | `reflect` |
| A fully specified one-line edit | do it, then the verification gate |

Nothing fits → use `work` with the closest playbook and say which steps you
dropped. Domain skills (framework, design, platform) are not sstack's; load them
alongside when the task touches their domain.

## Follow the playbook

Open a todo list. Copy the chosen playbook's steps (or the skill's steps) into it
**verbatim** before any task-specific items. A step you decide not to do stays in
the list, marked `skip: <reason>`. Repo overrides in `.sstack/playbooks/` apply on
top (see `work`).

## Gates

- A gate is a stop: report, then wait for the user. Gates belong to this session.
- Before any gate, read every child's report **and** the change itself: `git diff`,
  or `git -C <child worktree> diff` when the child ran in its own checkout. Never
  pass a child's self-report through as your own claim.
- A routed child never approves its own gate, never commits, never opens a PR.
- Irreversible or outward-facing actions (push, PR, deploy, delete data, messages
  to people) always need the user's explicit yes, even mid-playbook.
- Any ADE or config change you make ends with: ask the user, then `sstack-doctor --smoke`.

## Verification gate

Run the check, read its output, then claim. Never claim from "should work", a
child's summary, or a truncated tail. Check order:

1. The repo's existing tests (`[project].verify` in `.sstack/project.toml` first).
2. Typecheck / build.
3. A narrow command that exercises the change directly.
4. Manual check of the real surface (run the app, call the endpoint).

Report what you ran and what it printed. If a check could not run, say so plainly.

## Delegation

Dispatch a role; never pick a model by hand.

- Write the brief from [brief-template.md](../work/brief-template.md), then run
  `<sstack>/bin/sstack-dispatch <role> --brief <file> --report <file> [--title <t>]
  [--hint <kind>] [--files <paths>...]`. Roles: `scout`, `investigate`, `plan`,
  `implement`, `review`. Put briefs and reports under `.sstack/runs/<run-id>/`.
- Routing maps the kind (`--hint` or detected from `--files`) to a tier, then to a
  harness and model. `<sstack>/bin/sstack-dispatch routes` lists the routes;
  `--dry-run` prints the resolved one. Pass the kind from the plan.
- Read the exit code:
  - `0` — read the report, then verify it yourself.
  - `1` / `2` — stop at the next gate and report what failed; don't silently redo it
    here.
  - `3` — the role is local: do it in this session.
  - `4` — nothing started. Stdout is the payload `{ade, role, readonly, run_dir,
    calls}`:
    1. **Start** every call in `calls`, from that one payload: load its `tool` with
       `load_hint`, then call it with `args` unchanged.
    2. **Wait** for each child's own completion signal. Never poll.
    3. **Collect**: a read-only child usually runs in a mode that can't write files.
       If its report file is missing once it finishes, write the child's final
       message there yourself.
    4. **Record** each with the first exit that matches: `--exit 2` if the child
       timed out, `--exit 1` if it failed or left no report, else `--exit 0`. A `record` that exits `4` prints the next tier's payload: same
       procedure. Read each report and verify it — launch success is not task
       success.
- A write child may run in its own checkout (`isolation: "worktree"` on T3). That
  checkout starts from the last commit, so uncommitted edits and ignored files
  (`.sstack/runs/`) are not there. Give every brief and report an absolute path, and
  commit or otherwise make reachable whatever the child needs before dispatch. Once
  it finishes, review `git -C <child worktree> diff` (path or branch from the tool
  result) and bring the change into this checkout before the next gate.
- Headless dispatch blocks until the child finishes. To run several at once, start
  each in the background (`&` … `wait`, or the harness's background run).
- Delegate reading by volume: fan out only when the question needs about five or
  more sources (files, PRs, logs). Fewer → read them here.

## Principles

Read the principle file in full before applying it, and name the principle when it
changed a decision.

- [prove-it-works](principles/prove-it-works.md) — before saying done, or reporting any state.
- [fix-root-causes](principles/fix-root-causes.md) — debugging; any guard, retry or workaround.
- [laziness](principles/laziness.md) — sizing a diff, tempted to add a layer or option.
- [model-the-domain](principles/model-the-domain.md) — stateful or branchy code, a second boolean.
- [sequence-verifiable-units](principles/sequence-verifiable-units.md) — multi-step work, sweeps, stacking commits.
- [test-behavior-not-implementation](principles/test-behavior-not-implementation.md) — writing or keeping a test.
- [separate-before-serializing-shared-state](principles/separate-before-serializing-shared-state.md) — concurrent writers, parallel children.
- [guard-the-context-window](principles/guard-the-context-window.md) — large outputs, many files, long sessions.

## Harness

Skills use generic verbs: "ask the user", "plan gate", "todo list", "spawn a
native subagent", "end-of-session hook". On a given harness, read
`harness-notes/<harness>.md` for the concrete tool:
[claude](harness-notes/claude.md), [codex](harness-notes/codex.md),
[cursor](harness-notes/cursor.md), [pi](harness-notes/pi.md).
Browser, device and capture come from the active ADE's note; the harness note is
the fallback. Other harnesses: use their nearest equivalent and say which.

## Reply

Short declarative sentences. Lead with the outcome. Every claim carries its
evidence (command + result) or is labelled a guess. Link only things you produced
or read this session.

---
Adapted from pstack `poteto-mode` (michael-denyer/pstack-claude @ 91ab921, MIT),
superpowers verification-before-completion (MIT), and the user's phased-work.
