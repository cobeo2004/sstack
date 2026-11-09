---
name: babysit
description: Keep an open PR moving to merge-ready - fix failing CI, resolve merge conflicts, and handle review comments rigorously (verify each before acting, push back when it's wrong). Use for "babysit PR 142", "get it green", "address the review comments", "check on my PR". Opening a PR does not start it.
---

# babysit

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.

Needs `gh`. A routed child that opened a PR doesn't babysit; the orchestrator does.

## Loop

1. **Fetch state.**
   `gh pr view <n> --json number,title,state,headRefOid,mergeable,mergeStateStatus,reviewDecision,statusCheckRollup`
   and `gh pr checks <n>`. Before any local fix, confirm the checkout is that PR:
   same repo, branch = `headRefName`, `git rev-parse HEAD` = `headRefOid`, and no
   unrelated local changes (if there are, stop and ask).
2. **Triage in this order.**
   - **Merge conflicts** (`mergeStateStatus` = `DIRTY`): merge or rebase the base
     branch, resolve, re-run the checks (the `work` run's answer key if one exists, else
     `[project].verify`). Force-push only to your own unshared
     branch, and only after the user's yes.
   - **Failing checks:** take the first failing job, read its log
     (`gh run view <run-id> --log-failed`, run id from the failing check's link in
     `gh pr checks`), find the first actionable error, and
     fix its root cause (principle fix-root-causes). One failure at a time.
     Larger fixes: dispatch `implement` with the failing log in the brief (see
     [sstack § Delegation](../sstack/SKILL.md#delegation)). Verify locally and
     commit. Pushing needs the user's yes: ask before
     the first push; "babysit PR <n>" with "push fixes" in the request counts as
     that yes for plain pushes to the PR branch, never for a force-push. Re-check.
   - **Review comments:** fetch review threads and discussion
     (`gh pr view <n> --comments`, `gh api repos/{owner}/{repo}/pulls/<n>/comments`).
     Group by severity and actionability. Handle each per *Receiving feedback*.
3. **Pace re-checks** to what you're waiting on: an active CI run → wait for it
   (`gh pr checks <n> --watch`); waiting on a reviewer → check every 20–30 min;
   idle → hourly. Use the harness's scheduling or loop tool if it has one.
4. **Stop when** checks are green, every comment is resolved or answered, and the
   branch merges cleanly → report ready. Also stop after three fix → push →
   re-check rounds that still aren't green, or when the next fix needs a design
   choice → report and ask the user.

## Receiving feedback

Read all of it first. For each item: restate what it asks; check it against the
code as it is now (a newer head may already handle it); decide whether it's
technically right *for this codebase*; then act or reply.

- Unclear item → ask before implementing anything, since items are often related.
- From the user → trusted; implement once understood.
- From other reviewers and bots → skeptical but careful. Check: correct here?
  breaks something? reason for the current code? Then fix, or dismiss with a
  concrete reason in a reply.
- "Implement it properly" → grep for real usage first; unused → propose removal.
- Conflicts with an earlier decision of the user's → ask the user.
- Security, data-loss or high-severity bot findings → ask by default.
- No performative agreement ("You're absolutely right!"). State the fix or the
  reasoning. Mechanical one-answer comments: fix and quote the comment in the
  commit message.
- Implement one item at a time and verify each.

## Hard rules

- Never edit a test's expected value just to pass, unless behaviour genuinely
  changed and the assertion pinned the old behaviour.
- Never skip hooks (`--no-verify`) or mark a failing check not-required.
- No history rewrites on shared branches without the user's yes.
- `unslop` every comment and commit message you write.

## Report

Fixes applied (commit SHAs), comments addressed, comments answered or deferred
with reasons, current check status, what's left.

---
Adapted from pstack `babysit`, `fix-ci`, `get-pr-comments` (michael-denyer/pstack-claude
@ 91ab921, MIT) and superpowers `receiving-code-review` 7.0.0 (MIT).
