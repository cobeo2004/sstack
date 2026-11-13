---
name: wiki
description: Read and write the sstack wiki, the linked Markdown pages in .sstack/wiki/ (this repo) and ~/.sstack/wiki/ (every repo) that hold how parts connect, why they are this way, and gotchas the code doesn't show. Use for "add this to the wiki", "what does the wiki say about X", "fix stale wiki pages", "lint the wiki", and from work, reflect, how and why when a finding is worth keeping.
---

# wiki

`<sstack>` is the sstack repo root: two levels up from this file's resolved path.
Format, commands and lint rules: [the wiki guide](../../docs/guide/wiki.md). This
file says when to read, when to write and what belongs. Call it "the sstack wiki"
wherever `code-review-graph wiki` could be meant.

## Read cheaply

1. `index.md` first, one line per page; the router already read both. Never load
   every page.
2. Open a page only when its summary matches the task. Follow its links one hop
   at a time; `<sstack>/bin/sstack-wiki backlinks <page>` lists who points at it.
3. A `[stale]` page: files under its `paths` changed since `updated`. Read it, but
   trust the code where they disagree.

Dispatched children don't need to be told: dispatch adds every repo page whose
`paths` match the child's `--files` to its brief, like a `[practices]` doc. So keep
`paths` accurate. A page with no `paths` only reaches children through the index.

## When to write

| Trigger | Who |
|---|---|
| A run learned how parts connect, why a choice was made, or a gotcha | `work`, `pr` step |
| A correction or dead end that describes rather than instructs | `reflect` |
| "Remember how X works", "add this to the wiki" | this skill, directly |
| `how` or `why` produced an answer the code alone doesn't show | offer to save it here |
| A run changed files under a `[stale]` page's `paths` | update that page in `pr` |
| Setting up a repo | `setup` seeds a few pages |

Children never write pages: they put wiki-worthy findings in their report, and the
session that owns the run writes them.

## What belongs

- Yes: how parts connect across files, why it is this way (with the PR, ticket or
  commit), invariants, traps and their causes, where to start for a task.
- No: imperative rules (those are lessons, `reflect`), what one file plainly says,
  copies of docs (link them), secrets, anything that is only true for this branch.
- Repo or global: about this codebase → `<repo>/.sstack/wiki/`; holds in any repo →
  `~/.sstack/wiki/` (`$SSTACK_HOME/wiki/` when set). Never link across the two.

## Write

1. Search first: grep the index and pages for the topic. Update the page that
   covers it rather than adding a near-duplicate.
2. One topic per page, file name in kebab-case, at most 150 lines. Frontmatter:
   `summary` (one line, at most 120 characters: it is the index line), `paths` (the
   globs it is about, `, `-separated), `updated` (`git rev-parse --short HEAD` after
   you checked it against the code).
3. Link at least one related page to it and from it, `[name](name.md)`, so it is
   not an orphan. Cite code as `path:line` in backticks; those aren't links.
4. Fixing a stale page: re-read the code under its `paths`, correct the text, bump
   `updated`. If the topic is gone, delete the page and the links to it.
5. `<sstack>/bin/sstack-wiki index --scope <s>`, then `lint --scope <s>`. Fix every
   ERROR; a WARN is fine to leave with a reason.

Never edit `index.md` by hand, and never edit `lessons.md` here: `sstack-lessons`
owns it.

## Report

The pages added, updated or deleted (with scope), and the lint result.
