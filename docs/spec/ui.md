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
| `GET /api/runs` | `index.jsonl` lines grouped by `run_dir`, newest first, each with its `run.json` |

`<layer>` is `home`, `repo` or `local`, never `defaults`. `<kind>/<name>` as in `source()`:
`config`, `project`, `harnesses/<n>`, `roles/<n>`, `tiers/<n>`, `ades/<n>` (TOML only; hooks and
notes are never written). Names are checked against `[A-Za-z0-9_.-]+` (no `/`, no leading `.`).
