---
name: reflect
description: Turn the user's corrections and the agent's dead ends into lessons so mistakes aren't repeated, and turn repeated lessons into structural edits (a skill, AGENTS.md, a check) instead of more notes. Use on "reflect", "/reflect", "remember this", "remember how X works", after the user corrects you, or at the end of a task that hit a dead end.
---

# reflect

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.

Lessons live in plain files every harness reads: `<repo>/.sstack/wiki/lessons.md`
(repo) and `~/.sstack/wiki/lessons.md` (about the user / general practice; `$SSTACK_HOME/wiki/` when set). Use
`<sstack>/bin/sstack-lessons` to change them; don't hand-edit lesson lines.
Agents read only `accepted` lessons (the `sstack` router loads them).

## What counts

- **The user's corrections:** "don't do X", "I told you…", "use Y, not Z", a
  rejected approach with a reason.
- **Dead ends in the code:** an approach that failed here for a reason a future
  agent would hit again ("tests need `supabase start` first, else ECONNREFUSED").
- **Recurring review findings:** the same review finding (class, not instance)
  raised run after run — a repo lesson waiting to become a check. Recon patterns
  are not a lesson source.
- **A child's "Instructions that were wrong or stale":** each report line is
  evidence that a brief, skill or doc sent an agent the wrong way.

Not lessons: one-offs, facts already in `AGENTS.md`/`CLAUDE.md`/the code, generic
advice, anything secret. Scope: a lesson that names this repo's files, docs,
scripts, services or agent manual is `repo`, even when it is a preference.
`global` is only for rules that would hold in any repo.

## Descriptive findings go to the wiki

A finding that describes rather than instructs (how a part works, why it is this way, a gotcha and
its cause) is not a lesson. Write or update an sstack wiki page directly, with no pending step:
`<repo>/.sstack/wiki/` when it is about this repo, `~/.sstack/wiki/` when it holds in any repo. Never
link across the two. Frontmatter: `summary` (one line), `paths` (globs it is about), `updated`
(`git rev-parse --short HEAD`); link related pages as `[x](x.md)`. Then
`<sstack>/bin/sstack-wiki index --scope <s>` and `lint --scope <s>`. An explicit "remember how X
works" is the same. Imperative rules stay lessons.

## Manual flow

1. Review the session: the user's corrections, the dead ends, a review finding
   that recurred, and a child report's wrong-or-stale lines, with where each
   happened.
2. Propose **at most 3** lessons. Each is one line, imperative, specific, with
   evidence (what happened, when).
3. Record each as pending, pinned to the files it is about (`--path`, repeatable,
   glob) so it loads only where it applies:
   `<sstack>/bin/sstack-lessons add --scope repo "Run pnpm, not npm" --evidence "user, 2026-11-08 UNI-142" --path package.json --path "**/package.json"` (`**/` needs a directory, so name the root file too).
   Skip `--path` for a rule that holds repo-wide.
   `add` also records the commit it was learned at, so the router can mark it
   `[stale]` once those files change; a lesson with no `--path` always loads.
   The same text again bumps `seen` instead of duplicating, and keeps the paths and
   commit it was first recorded with.
4. Show them to the user. On "yes" → `<sstack>/bin/sstack-lessons accept <id> --scope <s>`;
   "no" → `<sstack>/bin/sstack-lessons forget <id> --scope <s>`. The dashboard can do the same.
   Never accept on the user's behalf.

## Repo lessons live in one AGENTS.md section

Repo lessons about how agents work in this repo go in exactly one section of
`AGENTS.md`, `## Things agents get wrong`, one line each:

```
- <the mistake agents make> — <the enforcer: a check, lint, test, or "none">
```

The enforcer is the point: a line whose enforcer is "none" is still a wish, and
says so honestly. Delete a line once a check prevents that mistake, so the section
stays short. Nothing of this kind goes anywhere else in `AGENTS.md`.

## Repeat → structure

When `add` prints `ENCODE` (the lesson's `seen` reached `[reflect] encode_at`,
default 2), more notes won't help. Propose one concrete edit that makes the
mistake hard to repeat, cheapest reliable first:

1. a check or script (a lint rule, a test, a verify command in
   `[project].verify`), when a machine can enforce it;
2. one line in `AGENTS.md`'s `## Things agents get wrong` section (see above), or
   a repo skill, for a repo lesson;
3. the owning sstack skill (`<sstack>/skills/<skill>/SKILL.md`), for a global one.

Show the diff. Apply it only on the user's yes, run the skill lint
(`python3 -m unittest discover -s <sstack>/tests -p test_skills.py`) after editing
an sstack skill, then mark it: `<sstack>/bin/sstack-lessons encode <id> --scope <s> --target <path>`.

## Automatic capture (opt-in)

With `[reflect] auto = true` and the end-of-session hook installed (see harness
notes; the installer prints the snippet), `bin/sstack-reflect-hook` runs the
`scout` role in the background over the transcript lines this session hasn't
reflected on yet (offsets in `.sstack/runs/reflect/state.json`) using the capture
brief below plus the known lessons of both scopes. It records new lessons as
`pending` and bumps `seen` for each `SEEN` line, so repeats reach `[reflect] encode_at`. It never accepts. Review
pending lessons at the start of the next task or in the dashboard.

## Capture brief

You are reviewing one finished agent session to find lessons. Read the
transcript file named below (JSON lines; user messages and tool results).

Find at most 3 lessons of these kinds: the user's corrections of the agent ("don't
do X", "use Y", a rejected approach with a reason), dead ends in the code that a
future agent would hit again with the reason, instructions that were wrong or
stale (a brief, skill or doc that sent the agent the wrong way), and a review
finding that has now come up in more than one run. Skip one-offs, generic
advice, anything already written in the repo's AGENTS.md or CLAUDE.md, and anything
secret (tokens, keys, personal data). The known lessons are listed below the
transcript path: skip any lesson already listed, even if worded differently, and
output `SEEN: <scope>:<id> | <evidence>` for it instead.

Do not edit any file. Output one line per lesson, exactly:

LESSON: <repo|global> | <one imperative sentence> | <evidence: what happened, where in the session>

A lesson that names this repo's files, docs, scripts, services or agent manual is
`repo`, even when it is a preference. `global` is only for rules that would hold
in any repo. If there are no lessons, output `NONE`. End with `PASS`.

---
Adapted from pstack `reflect` + `principle-encode-lessons-in-structure`
(michael-denyer/pstack-claude @ 91ab921, MIT) and orbyn reflect
(orbyn-dev/orbyn-fullstack-skills @ 185e5a5, MIT).
