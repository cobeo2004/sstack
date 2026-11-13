# Wiki

## What this is

The sstack wiki is a folder of short, linked Markdown pages about a codebase: how its parts connect,
why they are the way they are, and the gotchas the code doesn't show. Agents read a generated
`index.md` (one line per page) and open a page only when the task needs it, so the wiki stays cheap
to consult. `sstack-wiki` rebuilds the index, lists backlinks and lints the links. The dashboard
shows the same pages as a read-only link graph ([dashboard.md](dashboard.md)).

It is called "the sstack wiki" everywhere so it isn't confused with `code-review-graph wiki`.

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
```

## Where it lives

There are two wikis, one per scope, picked with `--scope repo` (the default) or `--scope global`:

- **repo**: `<repo>/.sstack/wiki/`, about this codebase.
- **global**: `~/.sstack/wiki/` (`$SSTACK_HOME/wiki/` when `SSTACK_HOME` is set), about you and
  practice that holds in any repo.

In a linked worktree, the repo wiki is the worktree's own `.sstack/wiki/` when it holds at least one
page. Otherwise it is the primary checkout's, when the primary has a `.sstack/` folder. An empty
folder in the worktree never hides the primary's pages.

## Page format

A page is any `*.md` file directly in the wiki folder, except `index.md`. There are no subfolders.
A page's name is its file name without `.md`. It starts with optional frontmatter:

```text
---
summary: How login sessions are minted and refreshed
paths: lib/auth/**, web/login.tsx
updated: 3f9c2ab
---
```

- `summary`: one line, at most 120 characters. It becomes the page's line in `index.md`.
- `paths`: the globs the page is about, separated by `, ` (comma and space).
- `updated`: the commit the page was last checked against (`git rev-parse --short HEAD`). When a
  file matching `paths` changed since that commit, the page is stale, and its index line ends
  ` [stale]`.

Link pages with ordinary relative links, `[tokens](tokens.md)`. Links inside code spans and code
blocks don't count, and neither do URLs. A link to a missing page inside the wiki folder is a
broken link. A link from one scope's wiki into the other's is a cross-scope link and is an error:
the repo wiki and the global wiki never link each other. Links that leave the wiki folder for
anything else (for example `../product.md`) are allowed and ignored.

## Commands

`sstack-wiki index` writes `index.md` from the page summaries. `sstack-wiki backlinks <page>`
prints the pages that link to a page. `sstack-wiki lint` checks links, the index and page size:

```sh
mkdir -p .sstack/wiki
printf -- '---\nsummary: How sessions are minted\npaths: lib/auth/**\nupdated: %s\n---\n\nTokens: [tokens](tokens.md).\n' "$(git rev-parse --short HEAD)" > .sstack/wiki/auth.md
printf -- '---\nsummary: Token format and rotation\n---\n\nUsed by [auth](auth.md).\n' > .sstack/wiki/tokens.md
sstack-wiki index
sstack-wiki backlinks tokens
sstack-wiki lint
```

```text
# expect
wrote <repo>/.sstack/wiki/index.md (2 pages, 0 stale)
auth.md
lint: 0 errors, 0 warnings
```

Lint prints `ERROR` lines, then `WARN` lines, then a count, and exits 1 when there is any error:

```sh
mkdir -p .sstack/wiki
printf -- '---\nsummary: A page with a dead link\n---\n\nSee [gone](gone.md).\n' > .sstack/wiki/a.md
sstack-wiki index
sstack-wiki lint   # exit 1
```

```text
# expect
ERROR a.md: broken link gone.md
```

Errors are a broken link, a cross-scope link, and an `index.md` that is out of sync with the pages
(also when it is missing). Warnings are an orphan page (nothing links to it), a summary over 120
characters, a page over 150 lines, a page with no frontmatter summary, stale markers in `index.md`
that are out of date (`WARN index.md: stale markers out of date; run sstack-wiki index`), and an old
lessons file next to the wiki copy. A commit that touches a page's `paths` makes lint warn until you
re-check the page, update its `updated`, and run `index` again.

`index` with no wiki folder exits 1. `lint` with no wiki folder prints `lint: no wiki at <dir>` and
exits 0.

## Committed or local only

`setup` asks whether to commit the wiki. Committed (recommended) writes nothing extra: the pages
are ordinary files in `.sstack/wiki/`. Local only adds `.sstack/wiki/` to `.git/info/exclude` (or
`.gitignore` if you prefer). `.git/info/exclude` is shared by every worktree of the repo, so a local
only wiki is hidden in all of them, and worktrees read the primary checkout's pages.

## Lessons inside the wiki

Lessons live in the wiki as `lessons.md` (`.sstack/wiki/lessons.md` and `~/.sstack/wiki/lessons.md`).
An old `.sstack/lessons.md` is still read until the next write, which moves it into the wiki with
every line kept. When both files exist the wiki copy wins and lint warns. `lessons.md` is one rule
per line, managed by `sstack-lessons`, so lint skips its frontmatter, size and orphan checks.

## Who reads it

The router reads both `index.md` files at the start of a task and opens a page only when the task
needs it. Dispatched children get the index paths in their brief. `sstack-dispatch` also adds every
repo page whose `paths` match the files the child was given to the brief's "Skills to use" list, the same
way as a `[practices]` doc, with a stale note when the page is stale. So there is no need to list
wiki pages in `[practices]`. `how` and `why` start from the pages that cover their subject.

## Who writes it

The `wiki` skill says when a page is worth writing and what belongs in it. These skills use it:

- `setup` seeds a few pages for a new or existing repo.
- `work` adds or updates pages in its `pr` step for what the run learned, and refreshes stale pages
  whose `paths` the run changed. Children don't write pages; they flag findings in their report.
- `reflect` writes descriptive findings as pages, and so does "remember how X works".
- `how` and `why` offer to save an answer the code alone doesn't show.

Writes are direct, with no pending queue: a page is edited like any file, then `sstack-wiki index`
and `lint` run.

## How to change this

The code is `lib/sstack_wiki.py` (page model, index, lint, CLI) and its wrapper `bin/sstack-wiki`.
The tests are `tests/test_wiki.py`. The dashboard endpoints are in `lib/sstack_ui.py` and their
contract in [docs/spec/ui.md](../spec/ui.md).
