# sstack-dispatch — contract

Owner: `lib/sstack_dispatch.py` (B2). Fixtures: `tests/fixtures/payloads/*.json` (exit-4 stdout),
`tests/fixtures/runs/` (stands for `<repo>/.sstack/runs/`: `index.jsonl` + run dirs).

## Route: `[dispatch] via` / `--via`

| via | behaviour |
|---|---|
| `auto` (default) | active ADE's delegate (docs/spec/ade.md); no ADE → the session harness's `[session]` ([below](#session-harness)); neither, or `kind = "none"` → headless. `delegate.kind` must be `tool`, `hook` or `none`; anything else is a config error (exit 1, nothing runs). `auto` never runs `[cli]` |
| `headless` | the harness's `headless`/`headless_readonly` argv, always. Hooks and CI use this (`--via headless`) |
| `local` | nothing runs; exit 3 (the agent does it in-session) |
| `ade-cli` | opt-in: the active ADE's `[cli] cmd` (T3: `t3 thread start …`, a new top-level thread) |

`--via` beats config; `main(argv)` honours it.

## `--step <name>`

A step folder (docs/spec/workflow.md) supplies what used to be per-call options:

| from the step | effect |
|---|---|
| `role` | the role: it wins over the positional; a step with no role (`gate`) keeps the CLI's |
| `brief.md` | the default brief; its absolute path goes into the payload `task` (`--brief` when the step has none) |
| `max_agents` | cap = `min(max_agents, rules.max_parallel)`; over-cap members queue, never drop |

The cap is the payload `max_parallel` and the headless pool's thread count. `max_agents = 0` is
inline: dispatch prints `local` and exits 3 without starting anything — the agent does the step
itself (it still takes the write lock when the role writes; see below). Without `--step`,
`rules.max_parallel` and the role's own config apply, exactly as before.

## Exit codes

| code | meaning |
|---|---|
| 0 | report written (panel: at least one member) |
| 1 | failure / config error / empty report |
| 2 | timeout (`[dispatch] timeout_min`): one deadline per member across hook `delegate` → run / `wait` → `collect`; on expiry the hook's `cancel` is called |
| 3 | run locally (`via = local`, role unset, harness `local`, a `--step` with `max_agents = 0`) |
| 4 | the agent must call a tool: stdout is the payload below; nothing was started |
| 5 | busy: another run holds this checkout's write lock (below); nothing was started |

## Run layout

```
.sstack/runs/
  index.jsonl                         one global index, every run, every member (append only)
  implement.lock                      the checkout's write lock (below); absent when nobody writes
  implement.lock.mutex                the short flock around every read-modify-write of it
  <task>/                             one top-level folder per task
    dispatch/
      <HHMM>-<role>/                  a dispatch whose --report folder is under this task
        run.json                      written at start (below)
        run.lock                      `record` holds an flock on it around its read-modify-write of run.json
        baseline.json                 read-only roles only (below)
        hook.<harness>-<model slug>[-<variant name>]/  $SSTACK_HOOK_STATE for hook ADEs
        brief.<variant name>.md       a stage variant's brief (below)
  <YYYYMMDD-HHMM>-<role>/             flat run: --report directly in runs/ or outside it (legacy shape)
  reflect/                            bin/sstack-reflect-hook
    state.json
    <YYYYMMDD-HHMMSS>/                one reflect pass; its dispatch nests in <pass>/dispatch/
  doctor/                             sstack-doctor smoke runs
    smoke-<YYYYMMDD-HHMM>/
      dispatch/<HHMM>-<role>/
```

When `--report`'s folder is **strictly below** `.sstack/runs/`, the dispatch folder is
`<that folder>/dispatch/<HHMM>-<role>[-n]/`: one top-level run folder per task. A report at
`.sstack/runs/<task>/reviews/r.md` nests at `.sstack/runs/<task>/reviews/dispatch/<HHMM>-review/`,
still inside the task. A report directly in `runs/` or outside it creates the flat
`<YYYYMMDD-HHMM>-<role>[-n]/` run dir as before. The `-2`, `-3` … collision counter is scoped to the
dispatch folder, so concurrent dispatches of one task do not make new top-level entries.

Every path stored in `run.json`, `index.jsonl` and the panel index is relative to the repo root when
it is inside the repo, else absolute. Reports go wherever `--report` says (often the run dir).
`index.jsonl`'s `run_dir` holds the nested path (`.sstack/runs/<task>/dispatch/<HHMM>-<role>`), never just its task.
Runs are grouped by that `run_dir`.

`run.json` (dispatch writes it at start, before any member runs; `record` reads it):

```json
{"role": "review", "members": ["codex/gpt-6.1-sol", "claude/opus"],
 "report_base": ".sstack/runs/task/dispatch/1200-review/r", "panel_report": ".sstack/runs/task/dispatch/1200-review/r.md",
 "started_at": 1794225600.0, "readonly": true, "title": "sstack review", "brief": "b.md",
 "route": "panel (--panel)", "ade": "t3", "via": "auto", "hint": null,
 "step": "review", "max_agents": 2}
```

Keys: `role`, `members`, `report_base`, `panel_report`, `started_at`, `readonly`, `title`, `brief`
(repo-relative like every path here), `route` (the routing reason), `ade` (adapter name, null when
none was used), `via` (`auto` | `headless` | `ade-cli`), `hint` (`--hint` or null), `no_escalate`
(`--no-escalate`: never escalate this run; sstack-doctor smoke), `step` (`--step` or null),
`max_agents` (the cap this dispatch used; an escalated run's payload carries it), `skills` /
`skills_missing` (only with skills; see Skills). Written later:
`escalated` (true once `record` or dispatch escalated; never twice) and `panel_written` (true once
the panel index was written; never rewritten).

`report_base` = `--report` minus `.md`; `panel_report` = `--report` when the default has 2+ members,
`<report_base>.panel.md` when only stage variants made the run multi-member, else null;
`started_at` = Unix seconds. A member is `<harness>/<model>`, `<harness>/default` when no model
is configured (the ADE call then omits `model`); split on the first `/` (models may hold `/`); a
stage variant's member adds `#<stage>/<name>`. Panel members report to
`<report_base>.<harness>-<model slug>.md` (slug: every char outside `A-Za-z0-9.-` → `-`).

## Stage variants

Config: docs/spec/config.md (stage variants). For `investigate`, `plan` and `review`, once the
default members are chosen (review: by `mode`, unchanged), every enabled variant whose `paths` /
`kinds` match the files adds its members after the default's. The role stays the stage
(`--role review`; never `review/security`), so variant members run read-only and, for review, a
member equal to the implementer (`roles/implement.toml`'s, or the one routed for these files) is dropped (a variant left with no member is
skipped). With no dispatched default (local), variants don't run.

| | default | variant `<stage>/<name>` |
|---|---|---|
| member key | `<harness>/<model>` | `<harness>/<model>#<stage>/<name>` |
| report | `--report` (default panel: `<report_base>.<h>-<m>.md`) | `<report_base>-<name>.md` (variant panel: `<report_base>-<name>.<h>-<m>.md`) |
| brief | the run's brief | `<run_dir>/brief.variant-<name>.md` = the run's brief + the variant's `skills` + `## Lens: <stage>/<name>` and its `.md` |
| hook state | `hook.<h>-<m slug>` | `hook.<h>-<m slug>-<name>` |
| index line, hook stdin | no `variant` key | `"variant": "<stage>/<name>"`; `harness`/`model` stay clean |

Order: default members first, then variants by stage and name. Headless runs every member on one
pool of `max_parallel` threads (`--step`'s cap, else `rules.max_parallel`). Escalation is judged on
the default members only: a run whose single default member fails escalates it once, variants or
not. Variants never escalate; a failed variant is a gap (`gap (no report)` in the panel index). The
panel index lists every member, variants included.

`baseline.json` (read-only roles; written with `run.json`):

```json
{"head": "<HEAD sha>", "status": "<git status --porcelain=v1 -z --untracked-files=all output>",
 "files": {"lib/x.py": "<sha256 hex>", "gone.txt": null},
 "index": {"size": 1024, "sha256": "<sha256 of .sstack/runs/index.jsonl>"}}
```

`status` is NUL-separated (`-z`: names unquoted, a rename entry is followed by its source path).
`index` is null when there was no index yet.

`files` = every tracked-dirty and untracked path in that status, hashed by content (null =
deleted). Check (`record`, and dispatch itself for headless runs): take the same snapshot again; a
path is changed when its hash differs, it appears or disappears in `files`, or its status line
differs; HEAD moving adds `HEAD <old>..<new>`. Excluded (sstack's own files, never the child's):
this run dir, every other run dir under `.sstack/runs/` (for a nested run, its whole top-level task
folder), every report path (each member report,
`panel_report`, the escalation's `<report_base>.failed.md`) and each one's `.err`.
`.sstack/runs/index.jsonl` may only grow: it counts as changed when its baseline content is no longer
a prefix of what is there (truncated or replaced), not when lines were appended.
`.sstack/runs/implement.lock` and its `.mutex` are sstack's own and never count. Changed paths,
sorted, go to `readonly_warning` and a `WARNING: read-only role changed the working tree:` block
(one path per line) appended to the report. Warns, never fails. Same check for
`readonly = "enforced"`.

## Skills

Owner: `lib/sstack_skills.py`. Keys: docs/spec/config.md (skill keys).

Union, in order, deduped: the role's `skills`, `[skills.kinds]` for the kind (`--hint` when it
names a kind, else detected from `--files`), then every `[practices]` glob matching a `--files` path.
Each name resolves to the first `<dir>/<name>/SKILL.md` across: each member harness's `skill_dirs`
(member order; no members → every configured harness), repo `.agents/skills`, `.claude/skills`,
`.pi/skills`, then `<sstack>/skills`. Doc paths / URLs pass through (relative → under the repo root).
Last, every repo sstack wiki page (`lib/sstack_wiki.py` `wiki_dir`) whose frontmatter `paths` match a
`--files` path is added as a read link, unless `[practices]` already names it; a stale page's link
ends ` (stale since <updated>: trust the code)`. A stage variant's own `skills` get no pages.

Empty union → nothing changes. Otherwise, after the run dir is made, dispatch writes
`<run_dir>/brief.skills.md` = the brief + this section, and stores its path as `run.json` `brief`
(headless stdin, hook `brief`, the exit-4 `task` and escalation all use it):

```
## Skills to use

Read each before starting.
- `tdd`: /home/u/.agents/skills/tdd/SKILL.md
- read: /repo/docs/web.md
- `ghost` not installed — carry on without it
```

A missing skill never fails the dispatch: stderr `sstack-dispatch: skill <name> not found`, and
`run.json` / every index line of the run carry `skills` (resolved names, docs included) and
`skills_missing` (both present only when the union is non-empty). `--dry-run` and the local route
(exit 3, after the `local` line) print one line each: `skills: <name> <path>`, `skills: read <link>`,
`missing skill: <name>`.

## Exit 4 payload

Dispatch creates the run dir (`run.json`, `baseline.json`) and bakes `--run-dir` into each `record`
command. Read-only calls merge `[delegate.readonly_args]` (never worktree isolation); write calls
merge `[delegate.write_args]` (T3: `isolation = "worktree"`). `{task}` in the args is the child's task
text, with absolute brief and report paths (worktree children don't see `.sstack/runs/`):
`Read the brief at <BRIEF> and do exactly what it says. Write your report to <REPORT>. If you cannot
write files, return the full report as your final message.` (the payload fixtures predate the last
sentence). Placeholders in fixtures: `<RUN_DIR>`,
`<BRIEF>`, `<REPORT>` (the `--report` path), `<REPORT_BASE>` (`report_base`); `{exit}` is filled by
the agent. A member the ADE cannot host (`[delegate.shell]`, docs/spec/ade.md) gets the shell
tool's call instead: `tool` = its `name`, `args` = `[delegate.shell.args]` with `{command}` the
member's headless line. A session-harness payload has `"ade": null` and `"session": "<harness>"`;
with an ADE it has no `session` key.

```json
{"ade": "t3", "role": "scout", "readonly": true, "run_dir": "<RUN_DIR>", "max_parallel": 4,
 "calls": [{"member": "claude/haiku", "tool": "delegate_task",
            "load_hint": "ToolSearch select:mcp__t3-code__delegate_task",
            "args": {"title": "sstack scout", "role": "research", "interactionMode": "plan",
                     "task": "Read the brief at <BRIEF> and do exactly what it says. Write your report to <REPORT>. If you cannot write files, return the full report as your final message.",
                     "target": {"providerInstanceId": "claudeAgent", "model": "claude-haiku-5-5", "options": {}}},
            "record": "sstack-dispatch record scout --report <REPORT> --member claude/haiku --exit {exit} --run-dir <RUN_DIR> --session-kind t3-thread --session '<CHILD_THREAD_ID>'"}]}
```

Unmapped model → passed through, `"note"` added to that call (fixture `t3-implement.json`).
`max_parallel` = `rules.max_parallel` (default 4), or the `--step` cap: the agent starts at most
that many calls at once and starts the next as each is recorded. Each call carries its own report and
brief (a stage variant's call names its `brief.variant-<name>.md`).
`--route` prints this shape, with the nested or flat `run_dir` it would use, and creates nothing (no
run dir, no `run.json`, no baseline, no index line).

## Session harness

Claude Code is a harness, not an ADE (an ADE is a workspace or control plane for running agents,
docs/spec/ade.md). Its own `[session]` table in `harnesses/<h>.toml` covers the no-ADE case:

```toml
[session]
detect = ["CLAUDECODE"]          # env markers: any one set → this harness runs the session

[session.agent]                  # starts only this harness's own members
name = "Agent"                   # the tool; load_hint, readonly = "instructed" as in [delegate]
[session.agent.args]             # args / write_args / models: as [delegate.args], [delegate.write_args], [models.<h>]
[session.agent.write_args]       # write roles: isolation = "worktree"
[session.agent.models]           # sstack alias → the tool's model

[session.shell]                  # every other harness's member: its headless command, backgrounded
name = "Bash"
[session.shell.args]             # {command} {title}
```

Only `via = auto` reads it, and only when no ADE is active (a detected ADE always wins; `ade = none`
and `SSTACK_ADE=none` also mean headless). The first harness whose `detect` marker is set is the
session harness. Dispatch builds the same tool calls as for an ADE from it, so isolation, shell
members and the write lock behave as docs/spec/ade.md says: a shell child edits this checkout and
is not isolated. `run.json` records `session`; `record` uses it to escalate. `sstack-dispatch ade`
reports ADEs only. `sstack-doctor` validates the table and WARNs when a template harness's
`[session]` is missing from yours (sync never rewrites an existing file).

## Write lock

One writer per checkout. `.sstack/runs/implement.lock` holds every live holder in one JSON object:

```json
{"holders": [{"owner": ".sstack/runs/20261110-fix-login",
              "run": ".sstack/runs/20261110-fix-login/dispatch/1610-implement",
              "role": "implement", "files": ["lib/x.py"], "started": 1794225600.0}]}
```

Every dispatch of a role that is not read-only (`READONLY_ROLES`: `scout`, `investigate`, `plan`,
`review`) takes it — `implement` or any custom writer role — including the local route (exit 3) and
inline steps. Every read-modify-write of the holder list (acquire, stale cleanup, release) runs under
an `fcntl.flock` on `.sstack/runs/implement.lock.mutex`, the primitive `record` takes on `run.lock`;
`sstack-workflow done` releases holders the same way (docs/spec/workflow.md). Read-only roles and
`--dry-run` / `--route` take nothing.

`owner` is the task run folder `--report` sits in, relative to the repo root: `.sstack/runs/<task>`
for a report anywhere below it (`.sstack/runs/<task>/reviews/r.md` → `.sstack/runs/<task>`), else the
report's own folder. A dispatch whose owner already holds the lock reuses that holder, so one
orchestrator serializes its own groups and never waits on itself. A **different** owner is refused —
exit 5, stderr `BUSY: <holder run> <files>; nothing started`, nothing created or started — when

- the ADE or session harness does not isolate write children: `write_args.isolation` unset (`cursor`,
  headless, local, a hook), or any member is one it runs as a shell command (`[delegate.shell]`,
  `[session.shell]`), or
- the live holders reach the step's `max_agents` (`1` when no `--step` named one), or
- `--files` overlap a holder's. A side with no `--files` is unknown, so it overlaps.

A holder leaves when the run's last `record` returns, when a headless, hook or `ade-cli` run
returns here, or — for local work, which has no run dir — when `sstack-workflow done` records the
step that took it. A holder older than `[dispatch] timeout_min` is dropped by the next dispatch. An
empty holder list removes both files again; a caller that locked a `.mutex` unlinked while it
waited re-opens the file now at that path and locks again.

## `record`

```
sstack-dispatch record <role> --report <p> --member <harness>/<model>[#<stage>/<name>] --exit <n> --run-dir <d> [--session <id> --session-kind <kind>]
```

0. `--session` and `--session-kind` go together or not at all. The id is 1-200 chars of
   `[A-Za-z0-9._:%-]`; the kind is `claude`, `codex`, `t3-thread`, `pi` or `other`. Anything else,
   or one flag without the other, exits 1 with a stderr message before anything is appended; so does
   the unfilled `<CHILD_THREAD_ID>` of a printed payload. A caller without an id omits both flags.
   `<d>` must be under `<repo>/.sstack/runs/` (flat or nested) and `--member` one of `run.json`
   `members`, else exit 1. The repo root is the parent of the nearest ancestor named `.sstack`.
   Steps 1–4 run under an flock on `<d>/run.lock`.
1. Reads `<d>/run.json`; appends one index line to `.sstack/runs/index.jsonl`, `secs` = now −
   `started_at`.
2. Read-only role: the baseline check above against `<d>/baseline.json`.
3. Member failed (`--exit ≠ 0`, or `--exit 0` with a missing or empty report), the run's ADE is a
   tool ADE, a single member, a higher tier on `tier_order`, `[rules] auto_escalate` and not
   `no_escalate`: prints the next exit-4 payload (one tier up) and exits 4.
   Once per run (`escalated`); the failed report moves to `<report_base>.failed.md`.
4. Panel (`panel_report` set): once the index holds a line from `<d>` for every member in
   `run.json`, that last `record` writes the panel index at `panel_report` (format below), from the
   latest line per member; once per run (`panel_written`).

Exit code: 4 when step 3 escalated; else, for the `record` that writes the panel index, 0 when any
member's line has exit 0, else 1; else the member's code: the `--exit` value when not 0, else 0
with a non-empty report and 1 without one. Step 0 failures exit 1.

Index line (one JSON object per line):

```json
{"ts": "2026-11-09T12:05:40", "task": "sstack review", "role": "review", "ade": "t3", "via": "auto",
 "harness": "claude", "model": "opus", "exit": 0, "secs": 340.0,
 "run_dir": ".sstack/runs/task/dispatch/1200-review", "report": ".sstack/runs/task/dispatch/1200-review/r.claude-opus.md",
 "route": "panel (--panel)", "readonly_warning": ["lib/sstack_config.py", "scratch.txt"],
 "session": {"id": "019a7c1e-5b0e-7f3a-9d2e-4c1b8a6f0e52", "kind": "claude"}}
```

`session` (`{"id", "kind"}`) only when the child's session is known: the `--session` flags of `record`
(the exit-4 payload's record command ends with `--session-kind t3-thread --session '<CHILD_THREAD_ID>'`,
which the caller fills with `delegate_task`'s `childThreadId`, or edits or drops for another
harness), or what a headless run captured ([below](#headless-session-capture)); a line without it
stays valid and means "unknown". `ts` = local time when the line is written; `ade` null when none was used; `skills` and
`skills_missing` are added when the run has skills; `variant` (`"<stage>/<name>"`) only on a stage
variant member's line.

### Headless session capture

Only a member that `go()` runs in-process (`headless`, not an exit-4 shell command, whose stdout is
the report) captures a session, from keys in `harnesses/<h>.toml`; a harness with neither key (a
user's own) behaves as before. The `claude` and `codex` keys below are built in (`SESSION_ARGS`,
overridden key by key by the harness file; `[]` turns one off). The dry run and `shell_command` never
show these args.
A hook's headless fallback (no action, or a failed hook) captures like headless; a hook's own `run` or async action records none.

- `session_id_args` (claude: `["--session-id", "{session_id}"]`): sstack makes up a UUID per attempt
  (an escalated retry has its own), adds the args before a trailing `-` or at the end, and records
  `{"id": <uuid>, "kind": <session_kind>}`.
- `session_events_args` (codex: `["--json", "-o", "{report}"]`): the child prints JSONL events,
  which go to `<report>.events.jsonl` (kept; never a read-only change) while the child writes the
  report itself as its final message. The id is the first `thread.started` event's string
  `thread_id`; non-JSON lines are skipped. No such event, or an id that fails the `record` rule:
  no `session` key, never a guess. A CLI that ignores these args (no JSON line, empty report) keeps
  its stdout as the report, as without them.

Panel index (`bin/sstack-reflect-hook` parses `: exit 0 → (.+)$`):

```
# review panel

- codex/gpt-6.1-sol: exit 0 → .sstack/runs/task/dispatch/1200-review/r.codex-gpt-6.1-sol.md
- claude/opus: exit 1 → gap (no report)
```

## `ade` subcommand

`sstack-dispatch ade` prints the active adapter:

```json
{"name": "t3", "why": "env T3CODE_THREAD_ID", "layer": "home",
 "delegate": "tool delegate_task", "readonly": "instructed",
 "browser": "tool: preview_* tools (see t3.md)", "device": "tool: …", "capture": "tool: …",
 "note": "~/.sstack/ades/t3.md"}
```

No ADE → `{"name": null, "why": "no adapter detected", …}` with the other fields null. A session
harness is not an ADE and never shows here.
