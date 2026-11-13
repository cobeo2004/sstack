---
summary: Symlink and name rules for the dashboard's file-reading endpoints (/api/wiki, lessons, config layers)
paths: lib/sstack_ui.py, lib/sstack_wiki.py
updated: fd96c9e
---
# Dashboard file safety

The dashboard serves files to a browser, so every read is pinned inside its folder:

- A repo's `.sstack` and `.sstack/wiki` may not be symlinks (400). `~/.sstack` may be, because
  people keep it in a dotfiles repo; `_check_layer` and `_wiki_scope` share this rule.
- `W.load` skips symlinked pages, so `/api/wiki` never parses a file outside the wiki.
- `/api/wiki/page?name=` accepts only a name from `W.load(d)`'s own listing. No regex: names come
  from the directory, so `..` and separators can't match, and non-ASCII names work.
- `ui/pages/wiki.js` puts page text in `textContent` only; page text is never HTML.

Found in review of the wiki change; the reasoning behind the layout is in
[wiki-internals](wiki-internals.md). Run-process gotchas are in [work-run-gotchas](work-run-gotchas.md).
