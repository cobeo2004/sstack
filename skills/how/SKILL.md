---
name: how
description: Explain how something in the codebase works, from source, with file:line citations - at the level of a senior engineer onboarding onto a subsystem. Use for "how does X work", "walk me through Y", "what happens when Z", and before any nontrivial change or architecture decision.
---

# how

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.

Build a working mental model, not annotated source. Every claim cites
`file:line`. Read-only. Start from the sstack wiki pages whose summary or `paths` cover the
subject; the code wins where they disagree.

## 1. Size it

If the scope is ambiguous, state your interpretation and go; the user can
redirect.

- **Simple** (one module, a utility, "how does function X work"): explore and
  explain it yourself in one pass. Go to step 4.
- **Complex** (a subsystem across files or services, a cross-cutting feature, an
  architectural overview): step 2. When in doubt, take the simple path.

## 2. Explore (complex only)

Split the question into 2–4 distinct angles (e.g. data model, request path,
background jobs, configuration). Give each a brief (from `<sstack>/skills/work/brief-template.md`)
asking for: entry points, the main types and their relationships, the control flow
with `file:line`, conventions, and surprises. Fan them out with `swarm` (role
`scout`). Exit 3 → explore the angles here in sequence. `code-graph` can list
callers, callees and impact quickly when the graph is built.

## 3. Synthesize (complex only)

Read every explorer report. Re-check the load-bearing claims against the source
yourself (open the cited lines). Merge into one explanation; resolve
contradictions by reading the code, not by picking a report.

## 4. Present

Use these sections, dropping any that don't apply:

- **Overview** — what it is and what it's for, in a paragraph.
- **Key concepts** — the types, states and terms a reader needs.
- **How it works** — the main flow, step by step, each step cited.
- **Where things live** — a short map of files and their roles.
- **Gotchas** — non-obvious behaviour, ordering, shared state, sharp edges.

Mark anything you inferred rather than read as inferred. A `diagram` is worth
offering when the flow has more than about five hops. When the answer holds something the code
doesn't show (how parts connect, a gotcha), offer to save it with `wiki`.

---
Adapted from pstack `how` (michael-denyer/pstack-claude @ 91ab921, MIT).
