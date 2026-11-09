# Doctor and smoke test

## What this is

`sstack-doctor` checks that the sstack config is usable: it loads, has no legacy files, every role
resolves, the harness CLIs are on `PATH`, the active ADE is known, and hooks are executable.
`sstack-doctor --smoke` goes further: it sends a canary brief through every routed role and member
on the real path and checks each one answered. The smoke test starts real child agents, so an agent
runs it only after asking the user and getting a yes. The contract is
[docs/spec/doctor.md](../spec/doctor.md).

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
```

## Run the static checks

```sh
sstack-doctor
```

Expected, exit 0:

```text
# expect
PASS config loads: config and ADEs parse
PASS no legacy files: none
PASS roles resolve: …
PASS harness CLIs: claude, codex, pi
PASS active ADE: …
PASS hooks executable: ok
```

Each check prints `PASS <check>: <detail>`, `WARN <check>: <detail>` or `FAIL <check>: <detail>`.
Exit 0 when all pass, 1 when any fails; `WARN` is advice and never changes the exit code — `entry
pointers` warns when an agent's global instruction file (`~/.claude/CLAUDE.md`,
`~/.codex/AGENTS.md`, `~/.cursor/AGENTS.md`, `~/.pi/agent/AGENTS.md`) lacks the line
`sstack-install` adds or has a contradicting rule above it.

| check | passes when | usual fix on FAIL |
|---|---|---|
| `config loads` | every layer's config and every `ades/*.toml` parses | fix the TOML file the message names |
| `no legacy files` | no old single-file config in any layer | `sstack-config migrate` ([configuration.md](configuration.md#migrate-an-old-config)) |
| `roles resolve` | every role in `roles/` resolves to members | fix the role file; a hint naming an undefined tier is an error |
| `harness CLIs` | argv[0] of each used harness's `headless` / `headless_readonly` is on `PATH` | install that CLI or route the role elsewhere |
| `active ADE` | `sstack-dispatch ade` runs | fix the adapter file it names |
| `hooks executable` | every `ades/*.hook` in use is executable | `chmod +x <hook>` |
| `entry pointers` | read-only: each agent's global instruction file that exists carries the sstack pointer above any competing "… first" / "without asking" rule | run `setup` and pick its machine rows, or put the sstack rule above the one it names; `WARN` keeps the exit code |

A failing check, for example a broken role file:

```sh
home="${SSTACK_HOME:-$HOME/.sstack}"   # your home layer
mkdir -p "$home/roles"
printf 'harness = \n' > "$home/roles/scout.toml"
sstack-doctor   # exit 1
```

Expected, exit 1:

```text
# expect
FAIL config loads: <home>/.sstack/roles/scout.toml: …
```

## Run the smoke test

Run it after setup, after `sstack-config migrate`, and after any ADE or config change, once the
user says yes.

```sh
sstack-doctor --smoke
```

Outside a tool ADE every dispatch runs headless and doctor prints the result itself. Expected
(exit 0):

```text
# expect
PASS implement pi/opencode-go/deepseek-v4.1-flash
PASS review codex/gpt-6.1-sol
PASS review claude/opus
PASS scout claude/haiku
PASS tree unchanged
```

How it works:

- it makes a smoke run dir `.sstack/runs/<YYYYMMDD-HHMM>-smoke/` holding a random token `T` and a
  `smoke.json`;
- read-only roles get the brief "Reply with the line `CANARY <T>` and change nothing";
- `implement` gets "Write `<smoke dir>/canary.txt` containing `<T>`, then reply `CANARY <T>`";
- every dispatch is `sstack-dispatch <role> … --title "sstack smoke" --no-escalate`, so a failing
  canary never spends a stronger tier.

A member passes when its report holds `CANARY <T>`, its index line has `exit: 0`, a read-only member
has an empty `readonly_warning`, and for `implement` `canary.txt` holds `T`. `tree unchanged`
passes when nothing outside this smoke test's run dirs changed (`index.jsonl` may only grow).
Cleanup removes the run dirs and keeps the index lines (tagged `task: "sstack smoke"`), even when
the smoke body fails.

## Smoke test in a tool ADE (exit 4)

Inside T3 Code (or Cursor) doctor can't start children itself. It prints the payloads and exits 4:

```json
{"smoke_run_dir": "<repo>/.sstack/runs/20261109-1200-smoke",
 "payloads": [{"ade": "t3", "role": "implement", "calls": [...]}, {"role": "review", ...}, {"role": "scout", ...}],
 "next": "make every call and its `record`, then: sstack-doctor --smoke --check <repo>/.sstack/runs/20261109-1200-smoke"}
```

The agent makes every call in every payload, runs each call's `record` (see
[dispatch.md](dispatch.md#exit-4-make-the-tool-calls)), then runs `--check`. This block plays the
agent's part with a script that answers each canary itself:

```sh
tmp=$(mktemp -d)   # outside the repo
trap 'rm -rf "$tmp"' EXIT
T3CODE_THREAD_ID=demo sstack-doctor --smoke > "$tmp/smoke.json"   # exit 4
cat > "$tmp/agent.py" <<'EOF'
import json, re, subprocess, sys
out = json.load(open(sys.argv[1]))
for p in out["payloads"]:
    for c in p["calls"]:
        task = c["args"]["task"]
        brief = re.search(r"brief at (\S+) and", task)[1]
        report = re.search(r"report to (\S+)\. If", task)[1]
        text = open(brief).read()
        token = re.search(r"CANARY (\w+)", text)[1]
        if (w := re.search(r"Write (\S+) containing", text)):
            open(w[1], "w").write(token + "\n")
        open(report, "w").write(f"CANARY {token}\n")
        subprocess.run(c["record"].replace("{exit}", "0"), shell=True, check=True)
print(out["smoke_run_dir"])
EOF
python3 "$tmp/agent.py" "$tmp/smoke.json" > "$tmp/smoke_dir"
sstack-doctor --smoke --check "$(cat "$tmp/smoke_dir")"
```

Expected: the same five `PASS` lines and exit 0:

```text
# expect
PASS implement pi/opencode-go/deepseek-v4.1-flash
PASS review codex/gpt-6.1-sol
PASS review claude/opus
PASS scout claude/haiku
PASS tree unchanged
```

Keep the payload file outside the repo, as here; a
file written into the tree during the run fails `tree unchanged`.

`--check` accepts only a direct child of `<repo>/.sstack/runs/` named `*-smoke`. It deletes only the
run dirs that its `smoke.json` names. Anything else is a FAIL and nothing is deleted.

Out of scope: git-ignored files, and stray edits by a child that works in its own worktree (T3
`implement` runs with `isolation = "worktree"`).

## Exit codes

| code | meaning |
|---|---|
| 0 | every check PASS |
| 1 | any FAIL, or `--smoke` outside a git repo |
| 4 | `--smoke` in a tool ADE: payloads printed; make the calls, then `--smoke --check <dir>` |

## How to change this

- Checks and smoke test: `lib/sstack_doctor.py`; entry point `bin/sstack-doctor`.
- Spec first: [docs/spec/doctor.md](../spec/doctor.md); a new check gets a row there and on this
  page.
- The canary harness used in tests: `tests/fakes/fake_agent.py` (`canary*` modes).
- Tests: `python3 -m unittest discover -s tests -p test_doctor.py`, then
  `python3 -m unittest discover -s tests -p test_docs.py`.
