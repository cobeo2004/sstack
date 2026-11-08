---
name: diagram
description: Draw an architecture, sequence, data-flow, or lifecycle/state diagram that reflects the real code. Grounds the picture in source first (how, code-graph), then renders it with the installed archify skill (HTML/SVG/PNG); falls back to a Mermaid block when archify isn't installed. Use for "diagram this", "draw the architecture", "show the request flow", "visualize X".
---

# diagram

A thin wrapper: sstack finds the truth, archify draws it. archify stays installed
from its own upstream; sstack doesn't copy it.

## 1. Pick the kind

- **Architecture / topology** — components, surfaces, stores, external services.
- **Sequence** — calls over time for one request or flow.
- **Data flow / lineage** — where data is produced, transformed, stored, read.
- **Lifecycle / state** — the states of one thing and the events between them.

One diagram answers one question. Say the question in one line before drawing.

## 2. Ground it in the code

Never draw from memory or from the README alone.

- Run `how` on the subsystem (or reuse a recent `how` answer) to get the real
  components and flow, each with `file:line`.
- If the graph is built, use `code-graph` for module dependencies and call paths.
- For a repo-wide picture, start from `.sstack/product.md` (surfaces and how they
  connect) and confirm each edge in code.
- Write the node and edge list first, each edge with its evidence (`file:line`, or
  "from product.md, unverified"). Unverified edges are drawn dashed or left out.

## 3. Render

- **archify installed** (look for an `archify` skill in the harness's skill list,
  or `~/.agents/skills/archify/SKILL.md`): load it and follow its workflow, giving
  it the kind, the question, and the node/edge list with evidence. Let archify
  validate and export (HTML; PNG/SVG when asked).
- **archify missing:** say so in one line, and emit a Mermaid block
  (`flowchart`, `sequenceDiagram` or `stateDiagram-v2`) built from the same
  list. Don't install anything unasked.

Save output under `docs/diagrams/` only if the user wants it kept in the repo;
otherwise in `.sstack/runs/<run-id>/`.

## 4. Report

The question, the file path(s), and which edges are unverified.

---
Wraps archify (tt-a1i, MIT), used as installed. Grounding steps follow pstack `how`
(michael-denyer/pstack-claude @ 91ab921, MIT).
