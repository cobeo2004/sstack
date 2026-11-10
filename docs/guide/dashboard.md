# Dashboard

## What this is

`sstack-ui` starts a local dashboard on `127.0.0.1`: a cockpit for the split config and the run
records. It shows every config file with the layer it comes from and lets you save a file to a
layer or reset it to the inherited one. It also shows the active ADE and its capabilities, run
timelines (members, route, ADE, reports, exits, read-only warnings), lessons you can accept or
forget, and the code graph. It is a stdlib server with no build step. Every request needs the token
it prints. The HTTP contract is [docs/spec/ui.md](../spec/ui.md).

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
```

## Start it

```sh
sstack-ui              # needs: a browser; runs until Ctrl-C
sstack-ui --port 8765  # needs: a browser; fixed port instead of a free one
```

It prints one line, `http://127.0.0.1:<port>/?t=<token>`. Open that URL. Repos come from
`~/.sstack/repos.txt` (`$SSTACK_HOME/repos.txt` when that is set), one absolute repo root per line; `setup` adds
the repo there. `repo=global` means no repo layers (home and defaults only).

## Pages

| page | shows | writes |
|---|---|---|
| Config | every thing (`config`, `project`, `harnesses/*`, `roles/*`, `tiers/*`, `ades/*`) with its winning layer | save to `home`, `repo` or `local`; reset to inherited (deletes that layer's file) |
| ADE | the `sstack-dispatch ade` output and the note text | nothing |
| Runs | `index.jsonl` grouped by top-level task, newest first; each task lists its dispatch runs with their `run.json` and shows its current step from `workflow.json` | nothing |
| Lessons | `.sstack/lessons.md` and `~/.sstack/lessons.md` | accept, forget |
| Graph | code graph status | rebuild (runs `code-review-graph build` or `update`) |

Rules for saves: never into `defaults/`, never a hook or a note (TOML only). Every save is checked
by the real loader on a staged copy of the layers first; a save that would break the config is
refused with HTTP 400 and nothing is written. Symlinked targets are refused.

## Use the API

The page is a thin client over a JSON API, so an agent can use the API directly. This block starts
the server, writes a role to the `local` layer, shows that a bad save is refused, resets it and
stops the server:

```sh
tmp=$(mktemp -d)   # outside the repo
sstack-ui --port 0 > "$tmp/ui.url" &
ui=$!
trap 'kill $ui; rm -rf "$tmp"' EXIT
cat > "$tmp/client.py" <<'EOF'
import json, sys, time, urllib.error, urllib.parse, urllib.request
url_file, repo = sys.argv[1:]
for _ in range(100):
    url = open(url_file).read().strip()
    if url:
        break
    time.sleep(0.1)
base, token = url.split("/?t=")

def call(method, path, body=None):
    q = urllib.parse.urlencode({"t": token, "repo": repo})
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(f"{base}{path}?{q}", data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)

status, ade = call("GET", "/api/ade")
assert status == 200 and "name" in ade, ade
role = "/api/config/local/roles/implement"
assert call("PUT", role, {"text": 'harness = "claude"\nmodel = "sonnet"\n'})[0] == 200
status, err = call("PUT", role, {"text": 'harness = "nope"\n'})
assert status == 400, err
print(err["error"])
assert call("GET", role)[1]["text"] == 'harness = "claude"\nmodel = "sonnet"\n'
assert call("DELETE", role)[1]["removed"] is True
assert call("GET", "/api/runs")[0] == 200
print("ok")
EOF
python3 "$tmp/client.py" "$tmp/ui.url" "$PWD"
```

Expected output, exit 0:

```text
# expect
ConfigError: unknown harness 'nope' (add harnesses/nope.toml)
ok
```

Endpoints (all need `?t=<token>`; `PUT`, `POST` and `DELETE` also need
`Content-Type: application/json`; add `repo=<repo root>` or `repo=global`):

| method + path | does |
|---|---|
| `GET /api/repos` | repos from `repos.txt` |
| `GET /api/config` | effective config plus each thing's source layer |
| `GET /api/config/<layer>/<kind>/<name>` | that layer's file: `layer`, `kind`, `name`, `path`, `text`, `exists` |
| `PUT /api/config/<layer>/<kind>/<name>` | body `{"text": "<TOML>"}`; validated, then written |
| `DELETE /api/config/<layer>/<kind>/<name>` | reset to inherited: deletes the layer file |
| `GET /api/ade` | `sstack-dispatch ade` output plus `note_text` |
| `GET /api/runs` | tasks newest first, each with its dispatch run groups: `run_dir`, its index `lines`, its `run.json` |
| `GET /api/lessons`, `POST /api/lessons/accept`, `POST /api/lessons/forget` | lessons |
| `GET /api/graph`, `POST /api/graph/rebuild` | code graph |

For `config` and `project` the path has no name: `/api/config/repo/config`. Errors are
`{"error": "…"}` with 400, 403 (bad token or bad `Host`) or 404.

## How to change this

- Server and API: `lib/sstack_ui.py`; entry point `bin/sstack-ui`.
- Front end, no build: `ui/index.html`, `ui/app.js`, one module per page in `ui/pages/*.js`
  (`config`, `ade`, `runs`, `lessons`, `graph`), and the colour and type tokens in `ui/tokens.css`
  (light and dark).
- A new page: add `ui/pages/<name>.js`, add its name to `known` in `ui/app.js`, add its nav button
  and `<section id="page-<name>">` to `ui/index.html`, add any endpoint to `GETS` or
  `POSTS` in `lib/sstack_ui.py` and a row to [docs/spec/ui.md](../spec/ui.md) and to the tables
  above.
- Tests: `python3 -m unittest discover -s tests -p test_ui.py`, then
  `python3 -m unittest discover -s tests -p test_docs.py`.
