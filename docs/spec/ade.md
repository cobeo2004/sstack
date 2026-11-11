# ADE adapters — contract

An ADE (agentic dev environment: T3 Code, Orca, Conductor, Cursor…) is
`ades/<name>.toml` + optional `ades/<name>.hook` (executable) + optional `ades/<name>.md` (note for
the agent: how browser/device/capture work there). Loaded by `sstack_config.ades()`
(docs/spec/config.md); acted on by `lib/sstack_ade.py` (B2). Fixtures: `tests/fixtures/ades/<case>/`
(`home/ades/*` + `expected.json`: `order`; `checks` = detection cases; hook cases: `delegate_exit`,
`delegate` | `delegate_stdout`, `wait` (exit codes in order), `collect_exit` + `report`,
`cancel_marker`, `falls_back_to`, `dispatch_exit` = what `sstack-dispatch` must return).

## Detection

Active ADE, first rule that applies:
1. env `SSTACK_ADE=<name>|none`;
2. config `ade = "<name>"|"none"` (forces, even when `auto = false`);
3. `ade = "auto"`: walk `ades()` in order, skip `auto = false`, first match wins; adapters with
   `fallback = true` come after every other one (order kept within each group). Match =
   any `[detect] env` variable set, or `[detect] hook = true` and `<hook> detect` exits 0.
No match → no ADE (delegation is headless).

## TOML

```toml
auto = true                     # false: never auto-detected (cursor ships this way)
# fallback = true               # tried after every non-fallback adapter (claude ships this way)

[detect]
env = ["T3CODE_THREAD_ID"]      # any present → match
# hook = true                   # or ask `<hook> detect`

[delegate]
kind = "tool"                   # tool | hook | none
name = "delegate_task"          # tool: the agent tool to call
load_hint = "ToolSearch select:mcp__t3-code__delegate_task"
readonly = "instructed"         # enforced | instructed (see Read-only below)
poll_s = 15                     # hook: seconds between `wait` calls (default 15)

[delegate.args]                 # tool: args template. String placeholders: {title} {brief} {report}
title = "{title}"               # {role} {ade_role} {provider} {model}; "{options}" as a whole
role = "{ade_role}"             # value becomes the effort options object.
task = "Read the brief at {brief} and do exactly what it says. Write your report to {report}. If you cannot write files, return the full report as your final message."
target = { providerInstanceId = "{provider}", model = "{model}", options = "{options}" }

[delegate.readonly_args]        # merged over args for read-only roles
interactionMode = "plan"

[delegate.write_args]           # merged over args for write roles (implement)
isolation = "worktree"

[delegate.roles]                # sstack role → {ade_role}
scout = "research"
implement = "implementation"

[delegate.shell]                # optional: members the ADE can't host (see below)
name = "Bash"
[delegate.shell.args]           # placeholders: {title} {command}
command = "{command}"
run_in_background = true
description = "{title}"

[providers]                     # harness → provider id; unmapped → harness name
claude = "claudeAgent"

[models.claude]                 # per harness: sstack model → ADE model id
haiku = "claude-haiku-5-5"      # unmapped → passed through + a note in the payload

[effort_option]                 # provider id → option id; options = {<id>: effort} when effort set
codex = "reasoningEffort"

[cli]                           # optional, used only by `[dispatch] via = "ade-cli"`
path = "$T3CODE_CLI_PATH"       # $VARS expand; empty → ~/.t3/bin/t3
cmd = ["{cli}", "thread", "start", "--provider", "{provider}", "--model", "{model}", "--title", "{title}", "--wait", ".", "-"]

[browser]                       # declared only — printed by `sstack-dispatch ade`, never executed
kind = "tool"                   # tool | command | none
summary = "preview_* tools (see t3.md)"
# [device] and [capture]: same shape
```

Read-only payloads never ask for worktree isolation.

**Shell members.** With a `[delegate.shell]` table, a member whose harness is not a key of
`[providers]` is not hosted by the ADE's agent tool (Claude Code's `Agent` starts only Claude). Its
call uses the shell tool instead: `command` = `cd <repo root> && SSTACK_REFLECT=1 <the harness's
headless argv> < <brief> > <report> 2> <report>.err`, shell-quoted. The agent runs it in the
background, waits for it to end, then runs the call's `record`. Without `[delegate.shell]` every
member goes to `[delegate]` as before.

**Isolation.** A write run counts as isolated (docs/spec/dispatch.md, write lock) only when
`[delegate.write_args]` sets `isolation` **and** every member is one the ADE hosts: a shell child
edits this checkout. Escalation after a failed write child makes the same call.

Read-only: `instructed` = the ADE is only told (plan mode, a prompt); `enforced` = the ADE itself
blocks writes (documentation only). There is no separate path: for both, `record` runs the same
tree check (docs/spec/dispatch.md) and warns on changes.

`<name>.hook` and `<name>.md` resolve per file, independently of `<name>.toml`: the nearest layer
holding that file wins. A user `ades/t3.toml` without `t3.md` keeps the built-in note; a user
`ades/t3.hook` applies to whichever `t3.toml` wins.

## Hook

Called once per member as `<hook> <capability>`, cwd = the dispatch cwd, JSON on stdin, JSON on
stdout. One mechanism for async; there is no start/wait/collect in TOML. Env `SSTACK_HOOK_STATE` =
`<run_dir>/hook.<harness>-<model slug>/` (`…-<name>/` for a stage variant's member; dispatch creates it, per member): hooks keep state there,
never in the cwd.

| call | stdin | result |
|---|---|---|
| `detect` | `{}` | exit 0 = match |
| `delegate` | `{role, readonly, member, brief, report, cwd, title}`, plus `variant` (`"<stage>/<name>"`) for a stage variant's member (`member` then ends `#<stage>/<name>`, `brief` is its own) | stdout one of below |
| `wait` | `{id}` | exit 0 done · 10 still running (re-polled every `[delegate] poll_s`) · other = failed → dispatch exit 1, no collect |
| `collect` | `{id}` | stdout = report; no report → exit 1 → dispatch exit 1 |
| `cancel` | `{id}` | called on timeout; best effort (fake hooks touch `$SSTACK_HOOK_STATE/cancelled`) |

`delegate` stdout:

```json
{"action": "run", "argv": ["orca", "…"]}        // sync: dispatch runs argv, brief on stdin, stdout = report
{"action": "async", "id": "job-1"}              // child started: wait … collect
{"action": "none", "note": "CONDUCTOR_API_KEY not set; running headless"}
```

Hook missing or not executable, non-zero exit or bad JSON from `delegate`, or `action: "none"` →
the member runs headless, with a note (the hook's `note`, or what went wrong). (`fallback = true`
in the TOML is about detection order only.) `[dispatch] timeout_min` covers start → collect; on expiry dispatch calls `cancel`
and exits 2.

## Built-ins (`defaults/ades/`)

| name | detect | delegate | auto |
|---|---|---|---|
| t3 | `T3CODE_THREAD_ID` | tool `delegate_task`, plan mode when read-only | yes |
| orca | `ORCA_AGENT_SESSION_ID` | hook (task-create → worker-start, check --wait, collect) | yes |
| conductor | `CONDUCTOR_SESSION_ID` | hook (CLI/API; no `CONDUCTOR_API_KEY` → none + note) | yes |
| cursor | — | tool `Task` (`readonly: true`) | no: set `ade = "cursor"` |
| claude | `CLAUDECODE`, after the others (`fallback`) | tool `Agent` for Claude members (worktree-isolated when writing); `Bash` in the background for the rest | yes |
