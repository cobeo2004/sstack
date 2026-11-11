# Dispatch

## What this is

`sstack-dispatch <role> --brief <file> --report <file>` hands one role's brief to the harness and
model that config picks for it, and writes a run record. It goes through the active ADE when there
is one (a T3 Code child task, an Orca worker), else it runs the harness CLI headless. Skills never
call it directly: the `sstack` router owns the procedure. This page is for running and debugging it
by hand. The contract is [docs/spec/dispatch.md](../spec/dispatch.md).

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
sstack-config sync >/dev/null          # your ~/.sstack profile, as sstack-install creates it
```

## Roles, members and panels

| role | read-only | template config (`defaults/roles/`, synced to `~/.sstack/roles/`) |
|---|---|---|
| `scout` | yes | `claude` / `haiku` |
| `investigate` | yes | `claude` / `sonnet` |
| `plan` | yes | `claude` / `opus` |
| `implement` | no | `pi` / `opencode-go/deepseek-v4.1-flash`, effort `high` |
| `review` | yes | `mode = "auto"`, panel `codex/gpt-6.1-sol` (effort `high`) + `claude/opus` |

A **member** is one `harness/model` pair, written `<harness>/<model>` (`<harness>/default` when no
model is set). A role resolves to one member, or to a **panel** of several. Review with
`mode = "auto"` runs one reviewer (never the implementer's model) and the full panel only for
`security`/`complex` work, diffs over `[rules] panel_diff_lines` (400), or `--panel`. `panel` works
on any read-only role; on `implement` it is a config error.

Which member runs, first match wins: a `--hint <name>` naming a `[hint.<name>]` table in the role
file, or one whose `paths` match `--files`; then the work kind (`--hint <kind>` or detected from
`--files`) mapped to a tier; then the role file itself. `sstack-dispatch routes` prints the tiers,
kinds and hints in effect.

Kind detection from `--files` (implement only, and only when tiers exist): `security` and `complex`
→ `tier.strong`; `frontend`, `backend`, `mobile` → `tier.standard`; `mechanical`, `docs` →
`tier.cheap`. A plain `.ts`/`.js`/`.mjs` file is `backend` under `server/`, `api/`, `functions/`,
`supabase/` or `db/`, and `frontend` anywhere else. A change where every file is prose is `docs`,
even when a path mentions auth. A `security` change ignores path hints that would downgrade it
unless the hint sets `override_security = true`. Untracked files under a hidden directory (`.omc/`,
`.cache/`) are not counted. `[routing.kinds]` in `config.toml` remaps a kind to your own tier
(`frontend = "ui-fast"`) or adds a kind name for `--hint` (`data = "local-gpu"`).

A failed single-member run is retried once, one tier up `[rules] tier_order`, and never onto the
implementer's model for a review (`[rules] auto_escalate`). The failed report is kept as
`<report minus .md>.failed.md`.

## Stage variants

`roles/<stage>/<name>.toml` adds a member to `investigate`, `plan` or `review`
([configuration.md](configuration.md#add-a-stage-variant)). When its `paths` or `kinds` match
the files (or it has neither), it runs beside the default, read-only, never as the implementer's
model for a review, in the same pool of `[rules] max_parallel`. Review `mode` still picks only the
default reviewer(s). With `--report r.md`:

| member | key | report | brief |
|---|---|---|---|
| default | `claude/opus` | `r.md` | the brief |
| variant `review/security` | `claude/opus#review/security` | `r-security.md` | the brief + `## Lens: review/security` + its `.md` |
| variant panel `review/ux` | `codex/x#review/ux` | `r-ux.codex-x.md` | as above |

The panel index lists every member (at `r.md` when the default is a panel, else at
`r.panel.md`). A failing single default still escalates once with variants alongside; variants
never escalate, and a failed variant shows as `gap (no report)`. `sstack-dispatch routes` lists each variant with its `when`,
members and layer, e.g. `review/security: auth changes → claude/opus (repo)`.

## Flags

| flag | meaning |
|---|---|
| `--brief <file>` | the task text, sent to the child |
| `--report <file>` | where the report goes; a panel writes `<report minus .md>.<harness>-<model slug>.md` per member and an index at `--report` |
| `--title <text>` | title for ADE tasks and the index line's `task` (default `sstack <role>`) |
| `--hint <name>` | a config hint or a built-in kind |
| `--files <paths…>` | files the work touches; used for kind detection (review defaults to `git diff`) |
| `--step <name>` | take the role, the brief and the concurrency cap from that step folder ([workflow.md](workflow.md)) |
| `--base <ref>` | review: diff base for detection |
| `--panel` | review: force the full panel from `roles/review.toml` (other roles ignore it) |
| `--via auto\|headless\|local\|ade-cli` | beats `[dispatch] via` |
| `--no-escalate` | never retry a failed member one tier up |
| `--dry-run` | print the route and the command; run nothing, write nothing |
| `--route` | print the exit-4 payload shape; create nothing |

## Pick the path: `via`

Set in `config.toml` as `[dispatch] via`, or per call with `--via`.

| via | what runs |
|---|---|
| `auto` (default) | the active ADE's delegate: tool → exit 4, hook → the hook. No ADE: the session harness's `[session]` (Claude Code: exit 4 with `Agent` and `Bash` calls), else headless |
| `headless` | always the harness's `headless` / `headless_readonly` argv. Use it in hooks and CI |
| `local` | nothing; exit 3, the agent does the work in its own session |
| `ade-cli` | opt-in: the active ADE's `[cli] cmd` (for T3, `t3 thread start …`, a new top-level thread) |

Read-only roles always use the harness's `headless_readonly` argv; a harness without one is a
config error (exit 1).

## Exit codes

| code | meaning | what the caller does |
|---|---|---|
| 0 | report written (panel: at least one member) | read the report |
| 1 | failure, empty report, or config error | read stderr and `<report>.err` |
| 2 | timeout (`[dispatch] timeout_min`, default 30) | the child was killed; retry or narrow the brief |
| 3 | run locally | do the work in this session; stdout is `local` |
| 4 | the agent must make tool calls; nothing started | follow the payload (next section) |
| 5 | `BUSY: <holder run> <files>; nothing started` — another run holds this checkout's write lock | wait for the holder to record its step or finish, then dispatch again |

```sh
printf 'List the files.\n' > brief.md
sstack-dispatch scout --brief brief.md --report scout.md                 # exit 0
sstack-dispatch triage --brief brief.md --report triage.md               # exit 3
sstack-dispatch scout --brief brief.md --report s.md --via local         # exit 3
T3CODE_THREAD_ID=demo sstack-dispatch scout --brief brief.md --report t3.md > "${TMPDIR:-/tmp}/payload.json"   # exit 4
T3CODE_THREAD_ID=demo sstack-dispatch scout --brief brief.md --report h.md --via headless
```

`triage` has no `roles/triage.toml` in any layer, so it runs locally. The last line runs headless
even inside T3 Code, because `--via` beats the ADE.

## Steps and caps

`--step <name>` takes the role, the brief and the concurrency cap from the step
folder ([workflow.md](workflow.md)) instead of retyping them: the role defaults to
the step's `role`, the brief to its `brief.md`, and the run's `max_parallel` is
`min(max_agents, [rules] max_parallel)`. `max_agents = 0` runs the step inline (exit
3, stdout `local`); `1` allows no concurrency; over-cap members queue in the
payload's `calls`, never drop. `[rules] max_parallel` stays the hard ceiling, so a
step can only lower it, and `sstack-doctor` WARNs when a step asks for more.

## One writer at a time

Every dispatch of a write role — any role not in the read-only list — takes this
checkout's lock at `.sstack/runs/implement.lock`, including local work (exit 3).
The holder is the task run folder the `--report` sits in, so one orchestrator
serializes its own groups without waiting on itself. Another owner gets exit 5 when
it can't safely run beside the holders:

- an ADE or session harness that does not isolate children, or a run with a shell member (`Bash`
  in bare Claude Code) → refused while any live holder exists;
- an isolating ADE → refused when the holders already reach the step's `max_agents`,
  or when its `--files` overlap a holder's files.

Refused prints `BUSY: <holder run> <files>; nothing started` and starts nothing.
The caller waits for the holder, then dispatches again. The lock is released by the
run's last `record`, by a headless return, or for local work by
`sstack-workflow done <step>` of the step that dispatched it; a holder older than
`[dispatch] timeout_min` is stale and ignored. Parallel implement is described in
[workflow.md](workflow.md) and `skills/work/steps.md`.

## Exit 4: make the tool calls

Inside a tool ADE (T3 Code, Cursor), or in bare Claude Code with no ADE, dispatch creates the run dir and prints one call per member:

```sh
printf 'List the files.\n' > brief.md
T3CODE_THREAD_ID=demo sstack-dispatch scout --brief brief.md --report scout.md > "${TMPDIR:-/tmp}/payload.json"   # exit 4
python3 -m json.tool "${TMPDIR:-/tmp}/payload.json"
```

Expected (`<repo>` is the repo root):

```text
# expect
{
    "ade": "t3",
    "role": "scout",
    "readonly": true,
    "run_dir": "<repo>/.sstack/runs/YYYYMMDD-HHMM-scout",
    "calls": [
        {
            "member": "claude/haiku",
            "tool": "delegate_task",
            "load_hint": "ToolSearch select:mcp__t3-code__delegate_task",
            "args": {
                "title": "sstack scout",
                "role": "research",
                "task": "Read the brief at <repo>/brief.md and do exactly what it says. Write your report to <repo>/scout.md. If you cannot write files, return the full report as your final message.",
                "target": {
                    "providerInstanceId": "claudeAgent",
                    "model": "claude-haiku-5-5",
                    "options": {}
                },
                "interactionMode": "plan"
            },
            "record": "sstack-dispatch record scout --report <repo>/scout.md --member claude/haiku --exit {exit} --run-dir <repo>/.sstack/runs/YYYYMMDD-HHMM-scout --session-kind t3-thread --session '<CHILD_THREAD_ID>'"
        }
    ]
}
```

The agent then, for each call:

1. loads the tool (`load_hint`) and calls `tool` with `args` exactly as given;
2. waits for the child; if the child returned its report as its final message instead of writing
   it, writes that text to the report path;
3. runs the call's `record` command with `{exit}` replaced by the child's result (0 ok, 1 failed,
   2 timed out) and `<CHILD_THREAD_ID>` replaced by the child's id from the tool result (T3:
   `childThreadId`). An agent that cannot name the child's session drops the two `--session` flags.

Write the payload outside the repo (as above): a file created in the tree during a read-only run
shows up in the read-only check.

## Record a run

`record` closes one member of a tool-delegated run. Here the child's work is simulated by writing
the report by hand:

```sh
printf 'List the files.\n' > brief.md
T3CODE_THREAD_ID=demo sstack-dispatch scout --brief brief.md --report scout.md > "${TMPDIR:-/tmp}/payload.json"   # exit 4
printf 'README.md\n' > scout.md
python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["calls"][0]["record"].replace("{exit}", "0"))' "${TMPDIR:-/tmp}/payload.json" > "${TMPDIR:-/tmp}/record.sh"
sh "${TMPDIR:-/tmp}/record.sh"
tail -n 1 .sstack/runs/index.jsonl
```

Expected: `record` exits 0 and appends an index line:

```text
# expect
{"ts": "…", "task": "sstack scout", "role": "scout", "ade": "t3", "via": "auto", "harness": "claude", "model": "haiku", "exit": 0, "secs": …, "run_dir": ".sstack/runs/YYYYMMDD-HHMM-scout", "report": "scout.md", "route": "role default", "readonly_warning": []}
```

What `record` does, in order (under a lock on `<run_dir>/run.lock`):

1. checks `--run-dir` is under `<repo>/.sstack/runs/` and `--member` is in its `run.json`, else exit 1;
2. appends one line to `.sstack/runs/index.jsonl`;
3. read-only role: compares the tree with `baseline.json`; changed paths go to `readonly_warning`
   and a `WARNING: read-only role changed the working tree:` block appended to the report (it warns,
   never fails);
4. the member failed (`--exit` not 0, or an empty report), the run's ADE delegates by tool,
   `[rules] auto_escalate` on, the run not `--no-escalate`, a single member and a higher tier on
   `[rules] tier_order`: moves the report to `<report_base>.failed.md`, prints the
   next exit-4 payload one tier up and exits 4 (once per run);
5. panel: when every member has an index line, writes the panel index at `--report` (once).

Its exit code:

| code | when |
|---|---|
| 0 | `--exit 0` and the report exists and is not empty |
| the `--exit` value | `--exit` was not 0 (and no escalation) |
| 1 | `--exit 0` but the report is missing or empty; or a bad `--run-dir` or `--member` |
| 4 | it escalated: the next payload is on stdout |
| 0 or 1 | the panel member whose `record` writes the panel index: 0 when any member succeeded, else 1 |

Escalation (step 4) only happens for a single-member run in a tool ADE, so a panel member never
exits 4.

## Run a panel

```sh
printf 'Review the diff.\n' > brief.md
sstack-dispatch review --brief brief.md --report review.md --panel
cat review.md
```

Expected: exit 0 and an index at `review.md`:

```text
# expect
# review panel

- codex/gpt-6.1-sol: exit 0 → review.codex-gpt-6.1-sol.md
- claude/opus: exit 0 → review.claude-opus.md
```

Inside T3 Code the same command exits 4 with two calls; the last `record` writes the index.

## Skills in the brief

Configure skills per role, kind and path ([configuration](configuration.md)). When any apply, the
child gets `<run dir>/brief.skills.md`: your brief plus `## Skills to use` with each skill's
absolute SKILL.md path. A skill that isn't installed adds a "not installed — carry on without it"
line, a `sstack-dispatch: skill <name> not found` line on stderr, and lands in the index line's
`skills_missing`. `--dry-run` and exit 3 print `skills:` / `missing skill:` lines; on exit 3, read
those skills before doing the work yourself. Contract: docs/spec/dispatch.md (Skills).

## Run dir and index

Every dispatch (except `--dry-run`, `--route` and exit 3) creates one dir. A report under a
task folder nests inside it; a report in `runs/` itself or outside it gets a flat run dir.

```text
.sstack/runs/
  index.jsonl                      one JSON line per member per run, append only
  <task>/                          one folder per task: briefs, reports, progress.md
    dispatch/
      <HHMM>-<role>/               taken → -2, -3 … appended
        run.json                   role, members, report_base, panel_report, started_at,
                                   readonly, title, brief, route, ade, via, hint, no_escalate
        run.lock                   held by `record`
        baseline.json              read-only roles: HEAD, git status, file hashes, index size
        hook.<harness>-<model slug>/   $SSTACK_HOOK_STATE for hook ADEs
  <YYYYMMDD-HHMM>-<role>/          flat run: --report directly in runs/ or outside it
    …                              the same files
```

When `--report`'s folder is strictly below `.sstack/runs/`, the run dir is
`<that folder>/dispatch/<HHMM>-<role>[-n]`: a report at `.sstack/runs/my-task/scout.md` nests at
`.sstack/runs/my-task/dispatch/<HHMM>-scout`. A report directly in `runs/` or outside it (as below,
`scout.md` in the repo root) creates the flat `<YYYYMMDD-HHMM>-<role>[-n]` as before. The `-2`,
`-3` counter is scoped to the dispatch folder, and `record` accepts any run dir under
`<repo>/.sstack/runs/`.

Index line keys: `ts`, `task`, `role`, `ade`, `via`, `harness`, `model`, `exit`, `secs`, `run_dir`,
`report`, `route`, `readonly_warning`, plus `skills` and `skills_missing` when the run has
skills, and `session` (`{"id", "kind"}`) when the child's session is known: from `record --session
<id> --session-kind <claude|codex|t3-thread|pi|other>`, or captured by a headless claude child (a
UUID sstack makes up and hands it) or codex child (the thread id in its JSON events). Paths are repo-relative when inside the repo. Add
`.sstack/runs/` to `.gitignore`.

```sh
printf 'List the files.\n' > brief.md
sstack-dispatch scout --brief brief.md --report scout.md
mkdir -p .sstack/runs/my-task
printf 'List the files.\n' > .sstack/runs/my-task/brief.md
sstack-dispatch scout --brief .sstack/runs/my-task/brief.md --report .sstack/runs/my-task/scout.md
find .sstack/runs -type d | sort
python3 -c 'import json; [print(json.loads(l)["role"], json.loads(l)["exit"]) for l in open(".sstack/runs/index.jsonl")]'
```

Expected: a flat `<YYYYMMDD-HHMM>-scout/` beside `index.jsonl`, a `my-task/dispatch/<HHMM>-scout/`,
and one index line per run:

```text
# expect
.sstack/runs
.sstack/runs/YYYYMMDD-HHMM-scout
.sstack/runs/my-task
.sstack/runs/my-task/dispatch
.sstack/runs/my-task/dispatch/HHMM-scout
scout 0
scout 0
```

## How to change this

- Dispatch, `record`, the run dir, the read-only check and the write lock: `lib/sstack_dispatch.py`;
  routing, kinds and tiers: `lib/sstack_route.py`; ADE payloads and hooks: `lib/sstack_ade.py`;
  step folders and caps: `lib/sstack_workflow.py` ([workflow.md](workflow.md)).
- Spec first: [docs/spec/dispatch.md](../spec/dispatch.md). Payload shapes are frozen fixtures in
  `tests/fixtures/payloads/*.json`; add a new fixture instead of editing one.
- The router's dispatch procedure (`## Delegation` in `skills/sstack/SKILL.md`) must keep naming
  `record` and exit `4` (`tests/test_skills.py`); no other skill may name `sstack-dispatch`.
- Tests: `python3 -m unittest discover -s tests -p test_dispatch.py`,
  `python3 -m unittest discover -s tests -p test_route.py`, then
  `python3 -m unittest discover -s tests -p test_docs.py`.
