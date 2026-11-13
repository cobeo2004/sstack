# Brief template

Write each brief to `.sstack/runs/<run-id>/<role>-<n>.brief.md` and pass it, and the
report path, as absolute paths: a write child's own checkout has neither the ignored
run dir nor your uncommitted edits. Then `dispatch <role>` (see
[sstack § Delegation](../sstack/SKILL.md#delegation)). Fill every `<…>`.

```markdown
# <role> brief — <ticket or task title>

## Goal
<The user's goal in one or two sentences, and the smallest change expected to meet it.>

## Lane
You are the <role> for this task. Stay in this lane: <what to do; for read-only
roles: "read and report only — do not edit files">.

## Context to read first
- Every AGENTS.md / CLAUDE.md from the repo root down to each touched path: the
  nearer one overrides the root.
- The `docs` entries in `.sstack/project.toml`, and `.sstack/product.md` (what the
  app is).
- The sstack wiki indexes, by path only: <absolute path of each `index.md` that exists, from
  `~/.sstack/wiki/` and the repo's `.sstack/wiki/`>. Open a page only when the work needs it.
- The nearest similar file to each one you'll change, and its test: match the
  naming, error style and helpers already there instead of inventing new ones.
- <specific files, docs, ticket text>

## The work
<For implement: the approved plan, verbatim, with exact files and the check for
each step. For scout/investigate: the questions, one per line. For review: the
diff range or PR and the lenses to apply.>

## Rules
- No commits, no pushes, no PR, no questions to the user. If blocked, say BLOCKED
  in the report with what you need.
- Write and run tests per `<sstack>/skills/work/testing.md`: code tests first,
  watched failing, then passing; browser/mobile checks on their surface, with a
  screenshot under the run dir. Include the real output.
- Don't edit tests listed as protected.

## Report (your final message)
1. **Files changed** — paths, or "none".
2. **What I did** — short.
3. **What I could not do** — and why.
4. **Instructions that were wrong or stale** — instruction, what was true, what I
   did instead (or "none"). Include sstack wiki pages that were wrong, and anything the code
   doesn't show that a page should say; don't edit the wiki yourself.
5. **Status** — `PASS`, `ISSUES` or `BLOCKED`, with evidence: each command run and
   its trimmed output.
```

The orchestrator reads the report **and** the change itself — `git diff`, or
`git -C <child worktree> diff` for a child in its own checkout — and re-runs the
decisive checks itself before any gate.
