# sstack-doctor — contract

Owner: `lib/sstack_doctor.py`, `bin/sstack-doctor` (C).

## Static checks (`sstack-doctor`)

Each prints `PASS|FAIL <check>: <detail>`; any FAIL → exit 1, else 0.

| check | passes when |
|---|---|
| config loads | `load(root)` and `ades(root)` raise nothing (every layer's `ades/*.toml` parses) |
| no legacy files | `legacy(root) == []` (else names `sstack-config migrate`) |
| roles resolve | `resolve()` succeeds for every role in `roles/` |
| harness CLIs | argv[0] of every used harness's `headless`/`headless_readonly` is on `PATH` |
| active ADE | `sstack-dispatch ade` runs; prints name, why, delegate, capabilities, note path |
| hooks executable | every `ades/*.hook` that `ades()` returns is executable |

## Smoke test (`sstack-doctor --smoke`)

Runs after setup, migrate, or an ADE/config change — **only after the agent asks the user and gets
a yes**. One dispatch per routed role/member through the real path (`via` as configured):

- smoke run dir: `.sstack/runs/<YYYYMMDD-HHMM>-smoke/` (docs/spec/dispatch.md run layout), holding a random token `T`.
- read-only roles get the canary brief: "reply with the line `CANARY <T>` and change nothing".
- implement gets: "write `<run dir>/canary.txt` containing `<T>`, then reply `CANARY <T>`".
- tool delegation: doctor prints the exit-4 payloads; the agent makes the calls and the `record`s,
  then runs `sstack-doctor --smoke --check <run dir>`.

A member PASSes when its report holds `CANARY <T>`, its index line exists with `exit: 0`, and (read-
only) `readonly_warning` is empty; implement also needs `canary.txt == T`. The tree outside the run
dir must be unchanged. Cleanup removes the run dir and its index lines.

Exit codes: 0 all PASS · 1 any FAIL · 4 payloads printed (tool delegation; agent continues).
