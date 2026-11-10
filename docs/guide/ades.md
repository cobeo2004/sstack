# ADEs

## What this is

An ADE (agentic dev environment) is the app your agent runs in: T3 Code, Orca, Conductor, Cursor,
or none (a plain terminal). sstack detects the active ADE and uses it to delegate a role as that
ADE's own child task instead of a headless CLI. An ADE adapter is `ades/<name>.toml`, an optional
executable `ades/<name>.hook`, and an optional note `ades/<name>.md` that tells the agent how
browser, device and capture work there. `sstack-dispatch ade` prints the active one. The contract
is [docs/spec/ade.md](../spec/ade.md).

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
sstack-config sync >/dev/null          # your ~/.sstack profile, as sstack-install creates it
```

## Built-in adapters

They ship in the template `<sstack>/defaults/ades/`; `sstack-config sync` copies the `.toml` and
`.md` files into `~/.sstack/ades/`, and a `.hook` resolves from the template.

| name | detected by | delegate | read-only | browser / device / capture |
|---|---|---|---|---|
| `t3` | env `T3CODE_THREAD_ID` | tool `delegate_task`; exit 4 payload | `instructed` (plan mode) | tools: `preview_*` / `device_*` / `preview_recording_*` |
| `orca` | env `ORCA_AGENT_SESSION_ID` | hook (`orca.hook`, async) | `instructed` | commands: `orca goto/snapshot/…` / `orca emulator` / `orca screenshot` |
| `conductor` | env `CONDUCTOR_SESSION_ID` | hook (`conductor.hook`); no `CONDUCTOR_API_KEY` → headless with a note | `instructed` | none |
| `cursor` | never auto-detected (`auto = false`) | tool `Task` with `readonly: true` | `instructed` | tool: Browser subagent / none / none |

Each built-in has a note beside it ([t3.md](../../defaults/ades/t3.md),
[orca.md](../../defaults/ades/orca.md), [conductor.md](../../defaults/ades/conductor.md),
[cursor.md](../../defaults/ades/cursor.md)) with `## Delegation`, `## Browser`, `## Device` and
`## Capture` sections. The agent reads the active one at task start.

## Detection order

The first rule that applies picks the ADE:

1. env `SSTACK_ADE=<name>` or `SSTACK_ADE=none`;
2. config `ade = "<name>"` or `ade = "none"` in `config.toml` (forces, even an adapter with
   `auto = false`);
3. `ade = "auto"` (the default): walk the adapters in order and take the first match. Order: the
   `local` layer, then `repo`, then `home`; within a layer your own adapters alphabetically, then
   the built-ins (alphabetical). Adapters with `auto = false` are skipped. A match is any `[detect] env` variable
   being set, or `[detect] hook = true` and `<hook> detect` exiting 0.

No match means no ADE: delegation runs the harness headless. A user `ades/t3.toml` replaces the
built-in `t3.toml` whole.

## Show the active ADE

```sh
sstack-dispatch ade
T3CODE_THREAD_ID=demo sstack-dispatch ade
T3CODE_THREAD_ID=demo SSTACK_ADE=none sstack-dispatch ade
SSTACK_ADE=cursor sstack-dispatch ade
```

Expected, in order, all exit 0 (`<sstack>` is where sstack is cloned):

```text
# expect
{
  "name": null,
  "why": "no adapter detected",
  "layer": null,
  "delegate": null,
  "readonly": null,
  "browser": null,
  "device": null,
  "capture": null,
  "note": null
}
{
  "name": "t3",
  "why": "env T3CODE_THREAD_ID",
  "layer": "home",
  "delegate": "tool delegate_task",
  "readonly": "instructed",
  "browser": "tool: preview_* tools (see t3.md)",
  "device": "tool: device_* tools (see t3.md)",
  "capture": "tool: preview_recording_* tools (see t3.md)",
  "note": "<home>/.sstack/ades/t3.md"
}
{
  "name": null,
  "why": "SSTACK_ADE=none",
  "layer": null,
  "delegate": null,
  "readonly": null,
  "browser": null,
  "device": null,
  "capture": null,
  "note": null
}
{
  "name": "cursor",
  "why": "SSTACK_ADE=cursor",
  "layer": "home",
  "delegate": "tool Task",
  "readonly": "instructed",
  "browser": "tool: Browser subagent (see cursor.md)",
  "device": "none",
  "capture": "none",
  "note": "<home>/.sstack/ades/cursor.md"
}
```

The output keys are `name`, `why`, `layer`, `delegate`, `readonly`, `browser`,
`device`, `capture`, `note`.

## Force or disable an ADE

```sh
home="${SSTACK_HOME:-$HOME/.sstack}"   # your home layer
mkdir -p "$home"
printf 'ade = "none"\n' > "$home/config.toml"
T3CODE_THREAD_ID=demo sstack-dispatch ade
```

Expected (abridged):

```text
# expect
"name": null,
"why": "ade = none",
```

Dispatch runs headless even inside T3 Code. Use `ade = "cursor"` to turn on Cursor, which has no reliable env marker. The env
var `SSTACK_ADE` beats the config for one command.

## Capabilities

sstack acts on two capabilities only: **detect** and **delegate**.

- `delegate.kind = "tool"`: dispatch starts nothing and exits 4 with a payload the agent turns into
  tool calls, then runs `sstack-dispatch record` ([dispatch.md](dispatch.md#exit-4-make-the-tool-calls)).
- `delegate.kind = "hook"`: dispatch calls `<name>.hook delegate` and runs or polls what it returns.
- `delegate.kind = "none"`: the member runs headless.

`browser`, `device` and `capture` are declared (`kind = "tool" | "command" | "none"` plus a
`summary`) and printed by `sstack-dispatch ade`; sstack never runs them. The note explains how the
agent uses them.

**Read-only.** `readonly = "instructed"` means the ADE is only told to stay read-only (for example
T3 plan mode). `"enforced"` means the ADE blocks writes itself. Both get the same check: `record`
compares the working tree with a baseline and appends a warning to the report if a read-only role
changed anything.

**Models.** `[providers]` maps a harness to the ADE's provider id, `[models.<harness>]` maps an
sstack model alias to the ADE's model id, and `[effort_option]` names the option that carries
effort. For T3: `claude` → `claudeAgent`, `haiku` → `claude-haiku-5-5`. An unmapped model is passed
through and the payload call gets a `"note"`.

## How to change this

- Built-in adapters: `defaults/ades/<name>.toml`, `.hook`, `.md`. Notes must keep the four
  `##` sections and stay under 120 lines (`tests/test_skills.py`).
- Detection and the `ade` output: `lib/sstack_ade.py`; adapter discovery: `ades()` in
  `lib/sstack_config.py`.
- Spec first: [docs/spec/ade.md](../spec/ade.md); detection fixtures go in a new case under
  `tests/fixtures/ades/<case>/`.
- Tests: `python3 -m unittest discover -s tests -p test_ade.py`, then
  `python3 -m unittest discover -s tests -p test_docs.py`.
- To add your own adapter, see [writing-an-ade.md](writing-an-ade.md).
