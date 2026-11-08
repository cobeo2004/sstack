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

1. Read the repo's `AGENTS.md` and/or `CLAUDE.md`.
2. Read `.sstack/product.md` if it exists. If it doesn't and the task is more than a
   one-liner, say once that `setup` would create it, then carry on.
3. Load accepted lessons from both scopes and follow them:
   `<sstack>/bin/sstack-lessons list --status accepted --scope repo` and
   `... --scope global`.
4. Say back, in one or two sentences, the user's goal and the smallest change you
   expect to meet it. Don't wait for confirmation unless the evidence rules out
   what they asked for; then show it and stop.

## Route the request

| Request | Go to |
|---|---|
| Make a repo agent-ready, new or existing ("set up", "onboard this repo") | `setup` |
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
- Before any gate, read every child's report **and** the real `git diff`. Never
  pass a child's self-report through as your own claim.
- A routed child never approves its own gate, never commits, never opens a PR.
- Dispatch exit 1 or 2 → stop at the next gate and tell the user what failed.
  Don't silently redo the work here.
- Irreversible or outward-facing actions (push, PR, deploy, delete data, messages
  to people) always need the user's explicit yes, even mid-playbook.

## Verification gate

Run the check, read its output, then claim. Never claim from "should work", a
child's summary, or a truncated tail. Check order:

1. The repo's existing tests (`[project].verify` in `.sstack/config.toml` first).
2. Typecheck / build.
3. A narrow command that exercises the change directly.
4. Manual check of the real surface (run the app, call the endpoint).

Report what you ran and what it printed. If a check could not run, say so plainly.

## Delegation

- Always delegate through the dispatcher, never by hand-picking a model:
  `<sstack>/bin/sstack-dispatch <role> --brief <file> --report <file> [--title <t>]`.
  Roles: `scout`, `investigate`, `plan`, `implement`, `review`.
- Write the brief from `<sstack>/skills/work/brief-template.md`. Put briefs and reports under
  `.sstack/runs/<run-id>/`.
- Exit `3` (prints `local`) → the role is local: do the work in this session.
- Exit `0` → read the report, then verify it yourself. Exit `1`/`2` → see Gates.
- `--dry-run` shows the resolved harness, model and transport without running.
- Delegate reading by volume: fan out only when the question needs about five or
  more sources (files, PRs, logs). Fewer → read them here.
- Inside T3 Code a non-read-only role becomes a visible thread automatically.

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
Other harnesses: use their nearest equivalent and say which.

## Reply

Short declarative sentences. Lead with the outcome. Every claim carries its
evidence (command + result) or is labelled a guess. Link only things you produced
or read this session.

---
Adapted from pstack `poteto-mode` (michael-denyer/pstack-claude @ 91ab921, MIT),
superpowers verification-before-completion (MIT), and the user's phased-work.
