# sstack-ui dashboard HTTP — contract (sketch; B4 refines)

Owner: `lib/sstack_ui.py`, `ui/**` (B4). Stdlib server on 127.0.0.1; every request carries the
token (`?t=<token>`); POST/PUT/DELETE also need `Content-Type: application/json`. `repo=<path>` or
`repo=global` (no repo layers) selects the repo. Errors: 400 `{"error": "…"}`, 403 bad token, 404.

| method + path | does |
|---|---|
| `GET /api/config/<layer>/<kind>/<name>` | that layer's file: `{"layer", "path", "text", "exists"}` |
| `PUT /api/config/<layer>/<kind>/<name>` | body `{"text"}`: writes the file, then runs `load()`; on `ConfigError` restores the old file and returns 400 |
| `DELETE /api/config/<layer>/<kind>/<name>` | "reset to inherited": deletes the layer file |
| `GET /api/config` | effective config + per thing `source()` layer (docs/spec/config.md) |
| `GET /api/ade` | `sstack-dispatch ade` output (docs/spec/dispatch.md) |
| `GET /api/runs` | `{"runs": [{"task", "ts", "children", "workflow"}]}`: index lines grouped by task (the top-level run folder), tasks newest first; each child is the old per-`run_dir` group object (`run_dir`, `lines`, `run`, `readonly_warning`, `ts`) with its `run.json`; a flat legacy run is a task with itself as its only child; `workflow` is the task folder's `workflow.json` (docs/spec/workflow.md), or `null` when it is missing or unreadable |
| `GET /api/wiki` | the sstack wiki of `repo=<root>` (`.sstack/wiki/`, or the primary checkout's when a worktree holds no page) or `repo=global` (`~/.sstack/wiki/`, `$SSTACK_HOME/wiki/` when set): `{"scope", "dir", "exists", "pages": [{"name", "summary", "paths", "updated", "stale", "orphan", "links", "backlinks", "lines"}], "lint": {"errors", "warnings"}}`; pages sorted by name; lint messages without the `ERROR `/`WARN ` prefix; a missing dir gives `exists: false`, `pages: []` and empty lint lists; a symlinked page is left out; a symlinked wiki dir, or a symlinked repo `.sstack`, is 400 |
| `GET /api/wiki/page?name=<page>` | one page: `{"name", "path", "text"}`, `text` the raw file; 400 when `name` is not a page listed by `GET /api/wiki` (so `index`, unknown names, `..` and separators are refused; non-ASCII names are fine), or the wiki dir, a repo's `.sstack` or the page is a symlink |

A nested `run_dir` such as `.sstack/runs/<task>/dispatch/<HHMM>-<role>` belongs to task
`.sstack/runs/<task>`; a flat `.sstack/runs/<YYYYMMDD-HHMM>-<role>` is its own task.

`<layer>` is `home`, `repo` or `local`, never the template. `<kind>/<name>` as in `source()`:
`config`, `project`, `harnesses/<n>`, `roles/<n>`, `tiers/<n>`, `ades/<n>` (TOML only; hooks and
notes are never written). Names are checked against `[A-Za-z0-9_.-]+` (no `/`, no leading `.`).
