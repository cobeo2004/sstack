# Writing an ADE adapter

## What this is

An ADE adapter teaches sstack how to detect an agentic dev environment and how to start a child
agent in it. You write it as files in any config layer, usually your home layer:
`~/.sstack/ades/<name>.toml` (required), `~/.sstack/ades/<name>.hook` (optional executable) and
`~/.sstack/ades/<name>.md` (optional note for the agent); the home layer is `$SSTACK_HOME` when set. No sstack code changes are needed.
A user adapter is checked before the built-ins and replaces a built-in of the same name. The full
contract is [docs/spec/ade.md](../spec/ade.md).

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
```

## Pick a delegate kind

| `[delegate] kind` | use it when | what dispatch does |
|---|---|---|
| `tool` | the ADE gives the agent a tool that starts a child (T3 `delegate_task`, Cursor `Task`) | starts nothing; exits 4 and prints a payload built from `[delegate.args]`; the agent calls the tool, then `sstack-dispatch record` |
| `hook` | the ADE has a CLI or API that starts a child | runs `<name>.hook delegate` and follows its JSON answer |
| `none` | the ADE can't start children | runs the harness headless |

Any other value, or `tool` without `[delegate] name`, is a config error: dispatch exits 1 and runs
nothing.

## TOML schema

Keys sstack reads. Every key is optional; `[delegate] kind` defaults to `"none"`, and
`kind = "tool"` also needs `[delegate] name`.

| key | type | meaning |
|---|---|---|
| `auto` | bool, default `true` | `false`: never auto-detected; only `ade = "<name>"` or `SSTACK_ADE` selects it |
| `[detect] env` | list of env var names | any one set → this ADE matches |
| `[detect] hook` | bool | `true`: also match when `<name>.hook detect` exits 0 |
| `[delegate] kind` | `tool` \| `hook` \| `none`, default `none` | see above |
| `[delegate] readonly` | `instructed` \| `enforced` | documentation only; `record` checks the tree either way |
| `[delegate] poll_s` | int, default 15 | hook: seconds between `wait` calls |
| `[delegate] name`, `load_hint` | string | tool: the tool name (required with `kind = "tool"`) and how the agent loads it |
| `[delegate.args]` | table | tool: argument template. Placeholders `{title}` `{brief}` `{report}` `{role}` `{ade_role}` `{provider}` `{model}` `{task}`; the whole value `"{options}"` becomes the effort options object |
| `[delegate.readonly_args]`, `[delegate.write_args]` | table | merged over `args` for read-only roles / for `implement` |
| `[delegate.roles]` | table | sstack role → `{ade_role}` |
| `[providers]`, `[models.<harness>]`, `[effort_option]` | tables | harness → provider id; sstack model → ADE model id; provider → effort option id |
| `[cli] path`, `cmd` | string, list | only for `[dispatch] via = "ade-cli"` |
| `[browser]`, `[device]`, `[capture]` | `kind` (`tool`\|`command`\|`none`) + `summary` | printed by `sstack-dispatch ade`, never run |

## Hook contract

sstack calls the hook once per member as `<hook> <capability>`, with the dispatch cwd, JSON on
stdin, and env `SSTACK_HOOK_STATE` set to a per-member dir inside the run dir
(`<run_dir>/hook.<harness>-<model slug>/`, plus `-<name>` for a stage variant's member). Keep
state there, never in the cwd.

| call | stdin | expected result |
|---|---|---|
| `detect` | `{}` | exit 0 = match (only with `[detect] hook = true`) |
| `delegate` | `{"role", "readonly", "member", "brief", "report", "cwd", "title"}`; a stage variant's member adds `"variant": "review/security"` and has its own `brief` | one JSON object on stdout (below) |
| `wait` | `{"id"}` | exit 0 done; 10 still running; anything else failed → dispatch exit 1 |
| `collect` | `{"id"}` | stdout is the report; exit 1 = no report → dispatch exit 1 |
| `cancel` | `{"id"}` | called on timeout; best effort |

`delegate` answers with one of:

```json
{"action": "run", "argv": ["orca", "..."]}
{"action": "async", "id": "job-1"}
{"action": "none", "note": "CONDUCTOR_API_KEY not set; running headless"}
```

- `run`: sync. Dispatch runs `argv` with the brief on stdin; its stdout is the report.
- `async`: the child started. Dispatch calls `wait` every `poll_s` seconds, then `collect`.
- `none`: the member runs headless and dispatch prints `sstack-dispatch: note: <note>`.

A missing or non-executable hook, a non-zero exit or bad JSON from `delegate` also falls back to
headless, with a note. `[dispatch] timeout_min` covers start to collect; on expiry dispatch calls
`cancel` and exits 2.

## Worked example: a hook adapter

This adapter, `myade`, matches when `MYADE_SESSION` is set. Its hook answers `run` with a stand-in
child (`sh -c 'echo MYADE REPORT; cat'`) so you can test the wiring without the real ADE. A real
adapter puts its own CLI in `argv`.

```sh
home="${SSTACK_HOME:-$HOME/.sstack}"   # your home layer
mkdir -p "$home/ades"
cat > "$home/ades/myade.toml" <<'EOF'
auto = true

[detect]
env = ["MYADE_SESSION"]

[delegate]
kind = "hook"
readonly = "instructed"
poll_s = 15

[browser]
kind = "none"
summary = ""
EOF
cat > "$home/ades/myade.hook" <<'EOF'
#!/bin/sh
# $1 = capability; JSON request on stdin; JSON answer on stdout.
case "$1" in
  delegate)
    cat > "$SSTACK_HOOK_STATE/request.json"
    echo '{"action": "run", "argv": ["sh", "-c", "echo MYADE REPORT; cat"]}' ;;
  *) exit 1 ;;
esac
EOF
chmod +x "$home/ades/myade.hook"
MYADE_SESSION=1 sstack-dispatch ade
printf 'Find the bug.\n' > brief.md
MYADE_SESSION=1 sstack-dispatch scout --brief brief.md --report my.md
cat my.md
cat .sstack/runs/*-scout/hook.claude-haiku/request.json; echo   # flat run dir: my.md is in the repo root
tail -n 1 .sstack/runs/index.jsonl
sstack-doctor
```

Expected, exit 0 (abridged; `<repo>` is the repo root):

```text
# expect
"name": "myade",
"why": "env MYADE_SESSION",
"layer": "home",
"delegate": "hook",
MYADE REPORT
Find the bug.
{"role": "scout", "readonly": true, "member": "claude/haiku", "brief": "<repo>/brief.md", "report": "<repo>/my.md", "cwd": "<repo>", "title": "sstack scout"}
{"ts": "…", "task": "sstack scout", "role": "scout", "ade": "myade", "via": "auto", …"exit": 0, …}
PASS hooks executable: ok
```

In order: `sstack-dispatch ade` picks `myade` from the home layer; `my.md` holds the stand-in child's
output, `MYADE REPORT` then the brief; `request.json` is what the hook got on stdin; the index line
records the ADE and `"via": "auto"`; `sstack-doctor` passes.

## Test the fallback

```sh
home="${SSTACK_HOME:-$HOME/.sstack}"   # your home layer
mkdir -p "$home/ades"
printf 'auto = true\n[detect]\nenv = ["MYADE_SESSION"]\n[delegate]\nkind = "hook"\n' > "$home/ades/myade.toml"
printf '#!/bin/sh\necho "{\\"action\\": \\"none\\", \\"note\\": \\"no API key\\"}"\n' > "$home/ades/myade.hook"
chmod +x "$home/ades/myade.hook"
printf 'Find the bug.\n' > brief.md
MYADE_SESSION=1 sstack-dispatch scout --brief brief.md --report n.md
tail -n 1 .sstack/runs/index.jsonl
```

Expected: stderr shows `sstack-dispatch: note: no API key`, exit 0, and the index line shows the
member ran on its harness CLI:

```text
# expect
{"ts": "…", "task": "sstack scout", "role": "scout", "ade": null, "via": "headless", …"exit": 0, …}
```

## Worked example: a tool adapter

For an ADE whose agent has a spawn tool, write only TOML. This one is selected with
`SSTACK_ADE=mytool` and maps a call onto a tool named `spawn_child`:

```sh
home="${SSTACK_HOME:-$HOME/.sstack}"   # your home layer
mkdir -p "$home/ades"
cat > "$home/ades/mytool.toml" <<'EOF'
auto = false

[delegate]
kind = "tool"
name = "spawn_child"
load_hint = "built in"
readonly = "instructed"

[delegate.args]
prompt = "{task}"
model = "{model}"

[delegate.readonly_args]
readonly = true
EOF
printf 'Find the bug.\n' > brief.md
SSTACK_ADE=mytool sstack-dispatch scout --brief brief.md --report t.md   # exit 4
```

Expected (abridged):

```text
# expect
"ade": "mytool",
"tool": "spawn_child",
"prompt": "Read the brief at <repo>/brief.md and do exactly what it says. Write your report to <repo>/t.md. If you cannot write files, return the full report as your final message.",
"model": "haiku",
"readonly": true
"note": "model haiku not in [models.claude]; passed through",
"record": "sstack-dispatch record scout --report <repo>/t.md --member claude/haiku --exit {exit} --run-dir <repo>/.sstack/runs/YYYYMMDD-HHMM-scout"
```

Exit 4: the payload's one call names `spawn_child` with `args` filled from `[delegate.args]` plus
`[delegate.readonly_args]`, a `"note"` (this adapter has no model map, so `haiku` passes through)
and the `record` command to run afterwards. `t.md` is in the repo root, so its run dir is flat; a
report under `.sstack/runs/<task>/` instead gets `<task>/dispatch/<HHMM>-scout`. What the agent does
next is in [dispatch.md](dispatch.md#exit-4-make-the-tool-calls).

## Write the note

`ades/<name>.md` tells the agent what it can't learn from the TOML. Built-in notes use four
sections, `## Delegation`, `## Browser`, `## Device`, `## Capture`; copy one from
`<sstack>/defaults/ades/` as a start. The note and the hook resolve per file: a user `ades/t3.toml`
without `t3.md` keeps the built-in note.

## How to change this

- This page documents user adapters; nothing in `lib/` needs to change to add one.
- To ship a built-in adapter: add `defaults/ades/<name>.toml`, its `.md` note (four sections, under
  120 lines) and any `.hook`; add a case under `tests/fixtures/ades/<case>/` with `expected.json`;
  test the hook against a fake CLI in `tests/test_ade.py`, never the real ADE.
- Contract changes start in [docs/spec/ade.md](../spec/ade.md); behaviour lives in
  `lib/sstack_ade.py`.
- Tests: `python3 -m unittest discover -s tests -p test_ade.py`,
  `python3 -m unittest discover -s tests -p test_skills.py` (note lint), and
  `python3 -m unittest discover -s tests -p test_docs.py` (runs the examples above).
