---
summary: How sstack_wiki, sstack_lessons and the dashboard share the wiki folder, and why lessons resolve differently
paths: lib/sstack_wiki.py, lib/sstack_lessons.py, lib/sstack_skills.py, lib/sstack_ui.py, ui/pages/wiki.js
updated: 8f32a81
---
# Wiki internals

- `lib/sstack_wiki.py` owns page parsing, links, the index, lint and the git staleness helpers
  (`stale`, `changed_since`). `sstack_lessons` imports those helpers; `sstack_wiki` never imports
  lessons, so there is no cycle.
- `lessons.md` is a node in the graph but not a normal page: fixed summary, no frontmatter, and lint
  skips its size, frontmatter and orphan checks. `sstack-lessons` owns its format.
- Lessons resolve with `repo_file(root, "wiki/lessons.md")` (the primary checkout), not `wiki_dir`.
  `wiki_dir` prefers a worktree's own wiki once it holds a page, and lessons auto-captured in a
  throwaway worktree would be deleted with it.
- The old `.sstack/lessons.md` moves on the next write: write the new file, then unlink the old one;
  an existing new file is never overwritten.
- `index.md` is generated and never a node. Lint ERRORs when the index lines differ, but only WARNs
  when just the ` [stale]` markers differ, because any commit touching a page's `paths` would
  otherwise fail lint.

- `sstack_skills.wiki_pages` turns page `paths` into `[practices]`-style read links for dispatched
  children, so pages never need listing in `.sstack/project.toml`. Only repo pages: global pages'
  `paths` would name files of no repo in particular.

The dashboard reads the same folder; see [dashboard-file-safety](dashboard-file-safety.md).
