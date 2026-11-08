---
name: reflect
description: Turn the user's corrections and the agent's dead ends into lessons so mistakes aren't repeated, and turn repeated lessons into structural edits (a skill, AGENTS.md, a check) instead of more notes. Use on "reflect", "/reflect", "remember this", after the user corrects you, or at the end of a task that hit a dead end.
---

# reflect

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.

Lessons live in plain files every harness reads: `<repo>/.sstack/lessons.md`
(repo) and `~/.sstack/lessons.md` (about the user / general practice). Use
`<sstack>/bin/sstack-lessons` to change them; don't hand-edit lesson lines.
Agents read only `accepted` lessons (the `sstack` router loads them).

## What counts

- **The user's corrections:** "don't do X", "I told you…", "use Y, not Z", a
  rejected approach with a reason.
- **Dead ends in the code:** an approach that failed here for a reason a future
  agent would hit again ("tests need `supabase start` first, else ECONNREFUSED").

Not lessons: one-offs, facts already in `AGENTS.md`/`CLAUDE.md`/the code, generic
advice, anything secret. Scope: `repo` if it's about this codebase, `global` if
it's about the user or general practice.

## Manual flow

1. Review the session: the user's corrections and the dead ends, with where each
   happened.
2. Propose **at most 3** lessons. Each is one line, imperative, specific, with
   evidence (what happened, when).
3. Record each as pending:
   `<sstack>/bin/sstack-lessons add --scope repo "Run pnpm, not npm" --evidence "user, 2026-11-08 UNI-142"`.
   The same text again bumps `seen` instead of duplicating.
4. Show them to the user. On "yes" → `<sstack>/bin/sstack-lessons accept <id> --scope <s>`;
   "no" → `<sstack>/bin/sstack-lessons forget <id> --scope <s>`. The dashboard can do the same.
   Never accept on the user's behalf.

## Repeat → structure

When `add` prints `ENCODE` (the lesson's `seen` reached `[reflect] encode_at`,
default 2), more notes won't help. Propose one concrete edit that makes the
mistake hard to repeat, cheapest reliable first:

1. a check or script (a lint rule, a test, a verify command in
   `[project].verify`), when a machine can enforce it;
2. the repo's `AGENTS.md` or a repo skill, for a repo lesson;
3. the owning sstack skill (`<sstack>/skills/<skill>/SKILL.md`), for a global one.

Show the diff. Apply it only on the user's yes, run the skill lint
(`python3 -m unittest discover -s <sstack>/tests -p test_skills.py`) after editing
an sstack skill, then mark it: `<sstack>/bin/sstack-lessons encode <id> --scope <s> --target <path>`.

## Automatic capture (opt-in)

With `[reflect] auto = true` and the end-of-session hook installed (see harness
notes; the installer prints the snippet), `bin/sstack-reflect-hook` runs the
`scout` role in the background over the session transcript using the capture
brief below, and records what it returns as `pending`. It never accepts. Review
pending lessons at the start of the next task or in the dashboard.

## Capture brief

You are reviewing one finished agent session to find lessons. Read the
transcript file named below (JSON lines; user messages and tool results).

Find at most 3 lessons of two kinds: the user's corrections of the agent ("don't
do X", "use Y", a rejected approach with a reason), and dead ends in the code that
a future agent would hit again, with the reason. Skip one-offs, generic advice,
anything already written in the repo's AGENTS.md or CLAUDE.md, and anything
secret (tokens, keys, personal data).

Do not edit any file. Output one line per lesson, exactly:

LESSON: <repo|global> | <one imperative sentence> | <evidence: what happened, where in the session>

Use `repo` for facts about this codebase and `global` for the user's preferences
or general practice. If there are no lessons, output `NONE`. End with `PASS`.

---
Adapted from pstack `reflect` + `principle-encode-lessons-in-structure`
(michael-denyer/pstack-claude @ 91ab921, MIT) and orbyn reflect
(orbyn-dev/orbyn-fullstack-skills @ 185e5a5, MIT).
