# Brief template

Write each brief to `.sstack/runs/<run-id>/<role>-<n>.brief.md` and pass it to
`<sstack>/bin/sstack-dispatch <role> --brief <file> --report <file>`. Fill every `<…>`.

```markdown
# <role> brief — <ticket or task title>

## Goal
<The user's goal in one or two sentences, and the smallest change expected to meet it.>

## Lane
You are the <role> for this task. Stay in this lane: <what to do; for read-only
roles: "read and report only — do not edit files">.

## Context to read first
- AGENTS.md / CLAUDE.md in the repo root.
- .sstack/product.md (what the app is).
- <specific files, docs, ticket text>

## The work
<For implement: the approved plan, verbatim, with exact files and the check for
each step. For scout/investigate: the questions, one per line. For review: the
diff range or PR and the lenses to apply.>

## Rules
- No commits, no pushes, no PR, no questions to the user. If blocked, say BLOCKED
  in the report with what you need.
- Run the checks named above and include the real output.
- Don't edit tests listed as protected.

## Report (your final message)
1. **Files changed** — paths, or "none".
2. **What I did** — short.
3. **What I could not do** — and why.
4. **Status** — `PASS`, `ISSUES` or `BLOCKED`, with evidence: each command run and
   its trimmed output.
```

The orchestrator reads the report **and** `git diff`, and re-runs the decisive
checks itself before any gate.
