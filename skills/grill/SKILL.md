---
name: grill
description: Shape a fuzzy idea or stress-test a plan by interviewing the user in rounds until every decision is settled, then write the decisions down as the ticket `work` runs from. Use for "brainstorm", "grill me", "stress-test this plan", "help me think this through", or when `work` finds no falsifiable definition of done.
---

# grill

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.

Interview the user until you reach a shared understanding. Map it as a **design
tree**: every decision branches into the decisions that hang off it. No code, no
plan, no edits until the user confirms the tree is done.

## Open

- **Fuzzy idea** (brainstorm: they can't yet say what done looks like): first say
  in one line that they can skip the questions and have you start (if they do, go
  straight to Done with GOAL and DONE WHEN only, from your best reading, and get
  their yes on those two lines). Then ask **one
  open question** that gets them describing a real moment or a concrete picture
  ("when do you find yourself wishing this existed?"). Their own words carry intent
  your options can't. Keep to one open question per message until you can name the
  goal and the first decisions; then switch to rounds.
- **A plan or design** (grill: the shape exists): go straight to rounds.

## Rounds

The **frontier** is every decision whose prerequisites are already settled: the
questions you can ask now without guessing at answers you haven't heard. Ask the
whole frontier in one round, numbered, each with your recommended answer, then wait.

```
**Q1 - <title>**: <question, with choices if there are any>

→ <your recommended answer>
```

Word each question so "yes" accepts your recommendation. A question that depends on
another one still open this round belongs to a later round. Each round of answers
pushes the frontier outward; recompute it and ask the next round.

## Settle the words too

When a round settles a term, add it to the repo's existing glossary — the one
`setup` linked in `.sstack/product.md` or `CONTEXT.md`/`GLOSSARY.md`/`docs/glossary*`.
One definition, then `_Avoid_:` with the words that mean something else here, so
later rounds and code use one name. No glossary in the repo → skip it and say so;
never create an empty one.

## Facts are yours, decisions are theirs

Never ask the user for something you could look up. When a frontier question needs
a fact from the code, the tools or the history, find it yourself (`how`, `why`,
`code-graph`), or for a many-source question dispatch `scout`
([sstack § Delegation](../sstack/SKILL.md#delegation)).
Don't block on it: only the questions downstream of a running lookup wait; ask the
rest of the frontier now. Each decision goes to the user, and you wait for it.

If running something would settle a question faster than talking (behaviour,
timing, does this layout feel right), build a throwaway prototype, show it, and
delete it once the question is answered.

## Done

The session is done when the frontier is empty: every branch visited, nothing
silently assumed. Then write `.sstack/runs/<slug>-<YYYYmmdd-HHMM>/decisions.md`:

- **PROBLEM** — what is wrong or missing today, in the user's words.
- **AFFECTED USERS AND SYSTEMS** — who feels it, and what it touches (skills, code,
  docs, services).
- **CONSTRAINTS** — what the solution must obey: house rules, spec, stack, cost.
- **GOAL** — one sentence, in the user's words.
- **DONE WHEN** — a falsifiable check (a command, a page state, a number).
- **REQUIREMENTS** — numbered `R1..Rn`, one testable promise each. `work` cites
  them from its plan and answer key; an uncited one is a requirement nobody built.
- **DECISIONS** — each settled question and its answer.
- **OUT OF SCOPE** — what was raised and ruled out.
- **OPEN** — anything the user deferred, plainly.

Show it and ask the user to confirm. On their yes, it is the ticket: hand off to
`work` with that run directory, and `work` reads `decisions.md` in Phase 0.

---
Adapted from mattpocock/skills `grilling` (MIT) and the opening move of
superpowers `brainstorming` (MIT).
