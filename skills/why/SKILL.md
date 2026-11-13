---
name: why
description: Find out why code is the way it is - the forces, decisions and incidents behind its shape - from git history, PRs, tickets, docs and chat, with every claim tagged by confidence. Use for "why do we do X", "why was this added", "is this still needed", or before changing code whose purpose is unclear.
---

# why

`how` answers what the code does; `why` answers what forces shaped it. Be a
careful investigator: separate what the record says from what you infer. Read
[references/epistemics.md](references/epistemics.md) before writing the answer.

## 1. Target and question

The **target** is code, a pattern, a feature or a decision. The **question** is a
rationale, a tradeoff, an edge case, an external constraint, dead code, or a
history sweep. Vague target → best guess from context, stated briefly, then go.
If the user embedded a hypothesis ("I assume it's for performance?"), treat it as
one candidate, not the answer.

## 2. Code anchor (always, here)

- Paths and line ranges; the key symbols.
- `git blame -L <a>,<b> <file>`; `git log --follow -p -- <file>`;
  `git log --oneline -20 -- <file>`; `git log -1 --format=%B <sha>`.
- PR numbers from commit subjects (`(#1234)`), then
  `gh pr view <n> --json title,body,author,mergedAt,labels,closingIssuesReferences,comments,reviews`.
- Linked ticket IDs.
- The sstack wiki pages whose `paths` cover the target: a past answer may already be there.

Trace back past the latest commit: today's shape is often an accretion.

## 3. Investigate by evidence source

List the evidence sources this session can reach: source control (always: git +
`gh`), ticket tracker, long-form docs, team chat, observability, error tracking,
analytics — usually through MCP tools. Give one child per available source (role
`scout`, via `swarm`), each owning exactly one source, with the anchor and the
question. Defensive code (retries, timeouts, null guards, flags, rate limits) →
ask the error-tracking and observability children to look for the incident.
Exit 3 or a single source → search them here in turn.

Skip a source only with a written reason: "no tool available here" (a gap) or
"provably irrelevant" (a high bar). A trivial single-commit target whose PR
already answers fully may be answered from the anchor alone; say so.

## 4. Synthesize

Every claim gets a tier from the epistemics file and phrasing to match. Check:
each claim has a citation or moves to inferred/hypotheses; code isn't cited as
evidence of its own intent; contradictions show both sources.

## Output

**The question** · **The code in question** · **What we found** (direct and
supported, cited) · **What we can reasonably infer** · **Competing hypotheses** ·
**What we don't know** (what was searched, with which terms) · **Sources
consulted** (one line per source, including empty and skipped ones, with reason)
· **Confidence summary**.

If the question precedes a change, end with **Preserve / Change / Avoid / Risk**
constraints for planning it. Offer to save the direct and supported findings with `wiki`, with
their sources; never save a hypothesis as fact.

---
Adapted from pstack `why` and its epistemics reference
(michael-denyer/pstack-claude @ 91ab921, MIT).
