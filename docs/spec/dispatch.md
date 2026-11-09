# sstack-dispatch — contract

Owner: `lib/sstack_dispatch.py` (B2). Fixtures: `tests/fixtures/payloads/*.json` (exit-4 stdout),
`tests/fixtures/runs/` (stands for `<repo>/.sstack/runs/`: `index.jsonl` + run dirs).

## Route: `[dispatch] via` / `--via`

| via | behaviour |
|---|---|
| `auto` (default) | active ADE's delegate (docs/spec/ade.md); no ADE or `kind = "none"` → headless. `delegate.kind` must be `tool`, `hook` or `none`; anything else is a config error (exit 1, nothing runs). `auto` never runs `[cli]` |
| `headless` | the harness's `headless`/`headless_readonly` argv, always. Hooks and CI use this (`--via headless`) |
| `local` | nothing runs; exit 3 (the agent does it in-session) |
| `ade-cli` | opt-in: the active ADE's `[cli] cmd` (T3: `t3 thread start …`, a new top-level thread) |

`--via` beats config; `main(argv)` honours it.

## Exit codes

| code | meaning |
|---|---|
| 0 | report written (panel: at least one member) |
| 1 | failure / config error / empty report |
| 2 | timeout (`[dispatch] timeout_min`): one deadline per member across hook `delegate` → run / `wait` → `collect`; on expiry the hook's `cancel` is called |
| 3 | run locally (`via = local`, role unset, harness `local`) |
| 4 | the agent must call a tool: stdout is the payload below; nothing was started |

## Run layout

```
.sstack/runs/
  index.jsonl                     one global index, every run, every member (append only)
  <YYYYMMDD-HHMM>-<role>/         one dir per dispatch; taken → -2, -3 … appended
    run.json                      written at start (below)
    run.lock                      `record` holds an flock on it around its read-modify-write of run.json
    baseline.json                 read-only roles only (below)
    hook.<harness>-<model slug>/  $SSTACK_HOOK_STATE for hook ADEs
```

Every path stored in `run.json`, `index.jsonl` and the panel index is relative to the repo root when
it is inside the repo, else absolute. Reports go wherever `--report` says (often the run dir).
Runs are grouped by the index line's `run_dir`.

`run.json` (dispatch writes it at start, before any member runs; `record` reads it):

```json
{"role": "review", "members": ["codex/gpt-6.1-sol", "claude/opus"],
 "report_base": ".sstack/runs/20261109-1200-review/r", "panel_report": ".sstack/runs/20261109-1200-review/r.md",
 "started_at": 1794225600.0, "readonly": true, "title": "sstack review", "brief": "b.md",
 "route": "panel (--panel)", "ade": "t3", "via": "auto", "hint": null}
```

Keys: `role`, `members`, `report_base`, `panel_report`, `started_at`, `readonly`, `title`, `brief`
(repo-relative like every path here), `route` (the routing reason), `ade` (adapter name, null when
none was used), `via` (`auto` | `headless` | `ade-cli`), `hint` (`--hint` or null). Written later:
`escalated` (true once `record` or dispatch escalated; never twice) and `panel_written` (true once
the panel index was written; never rewritten).

`report_base` = `--report` minus `.md`; `panel_report` = `--report` when there are 2+ members, else
null; `started_at` = Unix seconds. A member is `<harness>/<model>`, `<harness>/default` when no model
is configured (the ADE call then omits `model`); split on the first `/` (models may hold `/`). Panel members report to `<report_base>.<harness>-<model slug>.md` (slug: every char
outside `A-Za-z0-9.-` → `-`).

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
this run dir, every other run dir under `.sstack/runs/`, every report path (each member report,
`panel_report`, the escalation's `<report_base>.failed.md`) and each one's `.err`.
`.sstack/runs/index.jsonl` may only grow: it counts as changed when its baseline content is no longer
a prefix of what is there (truncated or replaced), not when lines were appended. Changed paths, sorted, go to
`readonly_warning` and a `WARNING: read-only role changed the working tree:` block (one path per
line) appended to the report. Warns, never fails. Same check for `readonly = "enforced"`.

## Exit 4 payload

Dispatch creates the run dir (`run.json`, `baseline.json`) and bakes `--run-dir` into each `record`
command. Read-only calls merge `[delegate.readonly_args]` (never worktree isolation); write calls
merge `[delegate.write_args]` (T3: `isolation = "worktree"`). `{task}` in the args is the child's task
text, with absolute brief and report paths (worktree children don't see `.sstack/runs/`):
`Read the brief at <BRIEF> and do exactly what it says. Write your report to <REPORT>. If you cannot
write files, return the full report as your final message.` (the payload fixtures predate the last
sentence). Placeholders in fixtures: `<RUN_DIR>`,
`<BRIEF>`, `<REPORT>` (the `--report` path), `<REPORT_BASE>` (`report_base`); `{exit}` is filled by
the agent.

```json
{"ade": "t3", "role": "scout", "readonly": true, "run_dir": "<RUN_DIR>",
 "calls": [{"member": "claude/haiku", "tool": "delegate_task",
            "load_hint": "ToolSearch select:mcp__t3-code__delegate_task",
            "args": {"title": "sstack scout", "role": "research", "interactionMode": "plan",
                     "task": "Read the brief at <BRIEF> and do exactly what it says. Write your report to <REPORT>. If you cannot write files, return the full report as your final message.",
                     "target": {"providerInstanceId": "claudeAgent", "model": "claude-haiku-5-5", "options": {}}},
            "record": "sstack-dispatch record scout --report <REPORT> --member claude/haiku --exit {exit} --run-dir <RUN_DIR>"}]}
```

Unmapped model → passed through, `"note"` added to that call (fixture `t3-implement.json`).
`--route` prints this shape, with the `run_dir` it would use, and creates nothing (no run dir, no
`run.json`, no baseline, no index line).

## `record`

```
sstack-dispatch record <role> --report <p> --member <harness>/<model> --exit <n> --run-dir <d>
```

0. `<d>` must be `<repo>/.sstack/runs/<id>` and `--member` one of `run.json` `members`, else exit 1.
   Steps 1–4 run under an flock on `<d>/run.lock`.
1. Reads `<d>/run.json`; appends one index line to `.sstack/runs/index.jsonl`, `secs` = now −
   `started_at`.
2. Read-only role: the baseline check above against `<d>/baseline.json`.
3. `--exit ≠ 0` and `[rules] auto_escalate`: prints the next exit-4 payload (one tier up) and exits 4.
   Once per run (`escalated`); the failed report moves to `<report_base>.failed.md`.
4. Panel (`panel_report` set): once the index holds a line from `<d>` for every member in
   `run.json`, that last `record` writes the panel index at `panel_report` (format below), from the
   latest line per member; once per run (`panel_written`).

Index line (one JSON object per line):

```json
{"ts": "2026-11-09T12:05:40", "task": "sstack review", "role": "review", "ade": "t3", "via": "auto",
 "harness": "claude", "model": "opus", "exit": 0, "secs": 340.0,
 "run_dir": ".sstack/runs/20261109-1200-review", "report": ".sstack/runs/20261109-1200-review/r.claude-opus.md",
 "route": "panel (--panel)", "readonly_warning": ["lib/sstack_config.py", "scratch.txt"]}
```

`ts` = local time when the line is written; `ade` null when none was used.

Panel index (`bin/sstack-reflect-hook` parses `: exit 0 → (.+)$`):

```
# review panel

- codex/gpt-6.1-sol: exit 0 → .sstack/runs/20261109-1200-review/r.codex-gpt-6.1-sol.md
- claude/opus: exit 1 → gap (no report)
```

## `ade` subcommand

`sstack-dispatch ade` prints the active adapter:

```json
{"name": "t3", "why": "env T3CODE_THREAD_ID", "layer": "defaults",
 "delegate": "tool delegate_task", "readonly": "instructed",
 "browser": "tool: preview_* tools (see t3.md)", "device": "tool: …", "capture": "tool: …",
 "note": "<sstack>/defaults/ades/t3.md"}
```

No ADE → `{"name": null, "why": "no adapter detected", …}` with the other fields null.
