---
name: unslop
description: Pre-PR cleanup of a diff and of prose (PR description, commit message, docs, replies). Removes AI code slop and needless comments without changing behaviour, then rewrites text to drop AI patterns. Use before every PR, on "deslop", "unslop", "clean this up", or when writing prose others will read.
---

# unslop

Two passes: code, then prose. Scope = the caller's files, else the branch diff
against its base (PR base, else the branch it was cut from, else the default
branch), including uncommitted changes.

## 1. Code

Remove slop the branch introduced. Touch only changed lines.

- Comments that restate the code, narrate steps (`// Step 1: …`), or don't match
  local style. Keep a comment only for a non-obvious *why* the code can't show,
  or a constraint imposed by something outside the code (a vendor rule, a
  protocol, "do not remove: X depends on this") — those stay.
- Defensive checks, `try`/`catch` and fallbacks that are abnormal for a trusted
  internal path. Validation at real trust boundaries stays.
- Casts (`as any`, `# type: ignore`, `!`) used only to silence the type checker;
  fix the type instead. Lint/type suppressions added by the branch: remove or
  justify each.
- Deep nesting that early returns flatten; one-caller wrappers; dead parameters;
  leftover debug output.
- Anything else out of keeping with the surrounding file.

Guardrails: keep behaviour unchanged unless fixing a clear bug. Small, focused
edits. Afterwards re-run the checks that verified the change (answer key, tests,
typecheck) and **revert any edit whose check fails**. Report in 1–3 sentences.

## 2. Prose

Rewrite PR text, commit messages, docs and replies. Keep the meaning and tone.

- Plain words: use (not utilize/leverage), help (not facilitate), many (not
  numerous), is/has (not serves as/boasts/features). Cut: additionally, crucial,
  delve, enhance, pivotal, showcase, robust, seamless, landscape, tapestry,
  testament, underscore.
- No "not just X, but Y", forced groups of three, synonym cycling, false ranges.
- No vague attribution ("experts say"). Name the source or cut it.
- No chatbot phrases ("I hope this helps", "Great question", "Certainly!"), no
  sycophancy, no generic conclusions ("the future looks bright").
- Filler: "in order to" → "to", "due to the fact that" → "because"; cut "it is
  important to note that". One hedge at most.
- Say what it does, not how it feels: name the mechanism or the number. If a
  sentence could appear unchanged in another project's docs, cut it.
- Short sentences, one idea each, active voice, whole sentences with articles.
- Formatting: sentence-case headings, no decorative emoji, straight quotes, bold
  sparingly, no "**Label:** restates the label" lists. Avoid em dashes and
  mid-sentence colons; use a period or a comma.

---
Adapted from pstack `deslop`, `no-comments` and `unslop`
(michael-denyer/pstack-claude @ 91ab921, MIT).
