---
name: review
description: Adversarial review of a working diff or a PR ("review", "review 142", "are we sure?", "check this before I merge"). Reviewers on a different model family try to break the change; only findings that reproduce against current code survive. Reports findings with evidence; never fixes. Also used by work's review step and for plan critique.
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
> and risks that need a future change to matter. Mark each finding `Important`
> (breaks the intent or a cited rule) or `Nit`, at most 5 nits, and don't inflate
> severity. "No findings" is a valid result. End with your **score, 1–10**, on the
> anchored rubric at the end of the lenses: 10 nothing found, 7–9 nits only, 5–6 a
> minor Important, 4 or less breaks the intent.

Dispatch `review` (see [sstack § Delegation](../sstack/SKILL.md#delegation)) with
this brief, the report path, and `--files` for a PR or committed range
(`git diff --name-only <base>...<head>`; the working diff is detected). Add
`--panel` when the user asked "are we sure?". By default one reviewer runs,
never the implementer's model. Stage variants (`roles/review/<name>.toml`) whose
`paths`/`kinds` match run beside it, each with its own lens and report
`<report-base>-<name>.md`; the panel index lists every member. The full panel runs in parallel, one report each,
only for `security`/`complex` changes, diffs over `rules.panel_diff_lines`, or
`--panel`. Exit 3 → review here yourself with the same brief, as a separate pass
after re-reading the diff fresh. Exit 1/2, or a member line ending in `gap (no
report)` → report that reviewer as a gap to the user; don't treat it as "no findings".
Read the default's report and every variant's, and merge them: a variant's
findings are weighed like any reviewer's, and a missing variant report is a gap.

## 3. Verify every finding

- Re-run each finding's command yourself against the **current head**. Keep it
  only if the output shows the failure and the failure breaks the intent.
- A newer head may already fix it: re-resolve each finding against current lines;
  drop or reclassify one the current code already handles. Never move an obsolete
  finding onto unrelated lines.
- Merge findings that share a root cause.
- Record a `verified` flag per finding: `true` only for one you reproduced in this
  pass, `false` for one that did not reproduce or that you could not run. Keep each
  reviewer's own score beside its findings; the caller writes `findings.json` for the
  run and hands it to the tracker, which recomputes every score after the drops:

  ```json
  [{"reviewer": "codex/gpt-6.1-sol", "score": 8,
    "findings": [{"title": "…", "severity": "Important", "verified": true,
                  "file": "lib/x.py", "where": "42", "evidence": "command + output"}]}]
  ```

  A verified Important caps that reviewer at 6; a reviewer whose Importants were all
  unreproduced is raised to at least 7 (10 when nothing verified is left); the final
  score is the lowest across reviewers. So an inflated score cannot survive a
  verification pass, and a padded one costs the caller a loop.

## 4. Then read others' comments

Only after your own pass (fresh eyes first): for a PR, read bot and human review
comments (`gh pr view <n> --comments`, `gh api repos/{owner}/{repo}/pulls/<n>/comments`).
Evaluate each on its merits with the same reproduce rule; include valid ones and
say they came from that reviewer.

## Output

- **Intent** — the restatement.
- **Score** — each reviewer's score and the final one (the lowest across reviewers),
  with the findings that moved it. `min_score` on the review step (default 5) is the
  bar: below it, or with any verified `Important` left, the step fails and routes
  back to `implement`. A change with only nits scores 7–9 and passes.
- **Scope** — base..head SHAs, files.
- **Findings** — for each: severity `Important` or `Nit`, `file:line`, command,
  output, how it breaks the intent or the cited rule, which reviewer found it, and
  its `verified` flag. At most 5 nits; only a verified `Important` blocks the
  caller's gate. "No verified findings" when none survive.
- **Dropped** — per reviewer, how many findings were dropped and why.
- **Gaps** — panel members and variants that failed or timed out (from the dispatch index).

---
Adapted from pstack `interrogate`, `thermo-nuclear-review` and `blast-radius`
(michael-denyer/pstack-claude @ 91ab921, MIT) and orbyn `pr-iteration`
(orbyn-dev/orbyn-fullstack-skills @ 185e5a5, MIT).
