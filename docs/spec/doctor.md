# sstack-doctor — contract

Owner: `lib/sstack_doctor.py`, `bin/sstack-doctor` (C).

## Static checks (`sstack-doctor`)

Each prints `PASS|WARN|FAIL <check>: <detail>`; any FAIL → exit 1, else 0. WARN is
advice: it prints, and the exit code does not change — other tools regenerate the file it
names, so a surprising WARN is a glance, not a broken config.

| check | passes when |
|---|---|
| config loads | `load(root)` and `ades(root)` raise nothing (every layer's `ades/*.toml` parses) |
| no legacy files | `legacy(root) == []` (else names `sstack-config migrate`) |
| roles resolve | `resolve()` succeeds for every role in `roles/`; the PASS line also lists each stage variant as `<stage>/<name> → <members> (<layer>)` |
| stage variants | no layer has a `roles/implement/` folder (FAIL: implement has no variants; use `[hint.*]`); every variant `.toml` has a `.md` lens, else `WARN stage variants: review/security has no roles/review/security.md lens (variant still runs)` |
| workflow | step folders resolve ([workflow.md](workflow.md)): FAIL on an `after`/`on_fail` naming no step, `on_fail` naming a disabled step, a cycle or two first steps, a custom step with both or neither of `brief.md`/`run.sh`, a `brief.md` without `role`, `min_score` outside `1..10`, or `pr` with `gate = false` / `enabled = false`; WARN when a step's `max_agents` exceeds `rules.max_parallel`; PASS names the chain (`recon → plan → …`) |
| harness CLIs | argv[0] of every used harness's `headless`/`headless_readonly` is on `PATH` |
| active ADE | `sstack-dispatch ade` runs; prints name, why, delegate, capabilities, note path |
| hooks executable | every `ades/*.hook` that `ades()` returns is executable |
| entry pointers | read-only, advice: every existing file among `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.cursor/AGENTS.md`, `~/.pi/agent/AGENTS.md` holds the sstack pointer (`<!-- sstack`, "start with the sstack skill", or "sstack first") with no competing precedence rule above it (`<tool> first`, "without asking", "do not stop to ask"). PASS names the files, or says `no agent instruction files`; a problem prints `WARN entry pointers: ~/.codex/AGENTS.md missing` or `… late (line 3: …)` |
| skills resolve | every configured skill name (role `skills`, `[skills.kinds]`, `[practices]`; docs skipped) has a SKILL.md on some harness's skill path (docs/spec/dispatch.md#skills); else `WARN skills resolve: <missing>` |

## Smoke test (`sstack-doctor --smoke`)

Runs after setup, migrate, or an ADE/config change — **only after the agent asks the user and gets
a yes**. One dispatch per routed role/member through the real path (`via` as configured):

- smoke run dir: `.sstack/runs/doctor/smoke-<YYYYMMDD-HHMM>[-n]/` (docs/spec/dispatch.md run layout), holding a random token `T`. Each role's dispatch nests under it at `dispatch/<HHMM>-<role>/`.
- read-only roles get the canary brief: "reply with the line `CANARY <T>` and change nothing".
- implement gets: "write `<run dir>/canary.txt` containing `<T>`, then reply `CANARY <T>`".
- tool delegation: doctor prints the exit-4 payloads; the agent makes the calls and the `record`s,
  then runs `sstack-doctor --smoke --check <run dir>`.

Smoke dispatches run with `--title "sstack smoke"` (their index lines' `task`) and `--no-escalate`
(a failing canary never spends a stronger tier). A route failure or an unexpected dispatch exit is a
FAIL.

A member PASSes when its report holds `CANARY <T>`, its index line exists with `exit: 0`, and (read-
only) `readonly_warning` is empty; implement also needs `canary.txt == T`. The tree outside this
invocation's smoke and dispatch run dirs must be unchanged (index.jsonl may only grow). Out of scope:
gitignored files, and a child working in its own worktree (T3 implement) — its stray edits aren't in
this tree.

Cleanup removes the smoke dir (including its nested dispatch run dirs) and then `doctor/` when it
is empty; index lines stay, tagged (index.jsonl is append-only). It also runs when the smoke body
raises. `--check` accepts only a direct child of `<repo>/.sstack/runs/doctor/` named
`smoke-<YYYYMMDD-HHMM>[-n]`, and deletes only nested run dirs inside it that its smoke.json names;
anything else is a FAIL and nothing is deleted.

## Prune runs (`--prune-runs`)

```
sstack-doctor --prune-runs <days> [--yes]
```

Candidates are the top-level entries of `.sstack/runs/` other than `index.jsonl`, `reflect/` and
`doctor/`. A candidate whose `progress.md` exists without a line starting `done:` is unfinished and
is kept. Age is the newest mtime of any file inside the run folder; only runs older than `<days>`
are listed, one per line as their repo-relative path (`.sstack/runs/<name>`). Nothing is deleted
without `--yes`; with it, each listed candidate is removed. Exit 0 on success.

Exit codes: 0 all PASS · 1 any FAIL · 4 payloads printed (tool delegation; agent continues).
