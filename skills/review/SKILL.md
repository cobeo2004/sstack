---
name: review
description: Adversarial review of a working diff or a PR ("review", "review 142", "are we sure?", "check this before I merge"). Reviewers on a different model family try to break the change; only findings that reproduce against current code survive. Reports findings with evidence; never fixes. Also used by work Phase 3 and for plan critique.
---

# review

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.

`review` → the working diff: the branch from its merge base with the base branch,
plus uncommitted changes. `review <PR#>` → that PR at its current head.
`review <plan file>` → critique a plan. Reports only; fixing is the caller's job.

## 1. Frame

- Resolve the scope exactly: base SHA, head SHA (for a PR: `gh pr view <n> --json
  headRefOid,baseRefName,title,body`), and the diff (`git diff <base>...<head>`).
  For the working diff, use `git diff <merge-base>` (staged + unstaged) and list
  untracked files with `git status --porcelain`; include them in the scope.
- A plan file: the scope is the plan. Findings are gaps, wrong ordering, steps
  that can't be verified, and claims the code contradicts (cite `file:line`).
  Steps 3–4 then check each finding against the code instead of a run.
- State the **intent** in one or two sentences, from the user's words, the
  commits, and the PR description. If intent is unclear, ask before reviewing.

## 2. Fan out

Write one brief (from `<sstack>/skills/work/brief-template.md`) with the scope, the intent, the
lenses in [references/lenses.md](references/lenses.md), and this instruction:

> Break this change. Only added or modified lines are in scope; don't report
> problems in untouched code. Each finding needs a way to prove it against the
> real code: a failing test, a repro script, or a command showing the wrong
> behaviour. Report each with a title, `file:line`, the exact command, the output
> the intent requires, and the actual output if your sandbox let you run it (you
> may be read-only; then say "not run"). Leave out style, naming,
> and risks that need a future change to matter. Don't inflate severity. "No
> findings" is a valid result.

Then: `<sstack>/bin/sstack-dispatch review --brief <run>/review.brief.md --report
<run>/review.report.md --title "<task> review"`, plus `--files` for a PR or
committed range (`git diff --name-only <base>...<head>`; the working diff is
detected) and `--panel` when the user asked "are we sure?". By default one
reviewer runs, never the implementer's model. The full panel runs in parallel,
one report each, only for `security`/`complex` changes, diffs over
`rules.panel_diff_lines`, or `--panel`. `--dry-run` prints the route first. Exit 3 → review here yourself with the same brief, as a separate pass
after re-reading the diff fresh. Exit 1/2, or a member line ending in `gap (no
report)` → report that reviewer as a gap to the user; don't treat it as "no findings".

## 3. Verify every finding

- Re-run each finding's command yourself against the **current head**. Keep it
  only if the output shows the failure and the failure breaks the intent.
- A newer head may already fix it: re-resolve each finding against current lines;
  drop or reclassify one the current code already handles. Never move an obsolete
  finding onto unrelated lines.
- Merge findings that share a root cause.

## 4. Then read others' comments

Only after your own pass (fresh eyes first): for a PR, read bot and human review
comments (`gh pr view <n> --comments`, `gh api repos/{owner}/{repo}/pulls/<n>/comments`).
Evaluate each on its merits with the same reproduce rule; include valid ones and
say they came from that reviewer.

## Output

- **Intent** — the restatement.
- **Scope** — base..head SHAs, files.
- **Findings** — for each: severity (high / medium / low, honest), `file:line`,
  command, output, how it breaks the intent, which reviewer found it.
  "No verified findings" when none survive.
- **Dropped** — per reviewer, how many findings were dropped and why.
- **Gaps** — panel members that failed or timed out (from the dispatch index).

---
Adapted from pstack `interrogate`, `thermo-nuclear-review` and `blast-radius`
(michael-denyer/pstack-claude @ 91ab921, MIT) and orbyn `pr-iteration`
(orbyn-dev/orbyn-fullstack-skills @ 185e5a5, MIT).
