# Contributing

## What this is

How to change sstack itself: where things live, how to test them, and the rules every change
follows. It is written for both people and coding agents. sstack has no dependencies beyond Python
3.11+ and git, and no build step. The tests never call a real model or a real ADE CLI.

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
```

## Repo layout

| path | holds |
|---|---|
| `bin/` | entry points: `sstack-dispatch`, `sstack-config`, `sstack-doctor`, `sstack-ui`, `sstack-lessons`, `sstack-worktree`, `sstack-install`, `sstack-pr-media`, `sstack-reflect-hook` |
| `lib/` | the code behind them: `sstack_config.py` (loader), `sstack_configcli.py`, `sstack_ade.py`, `sstack_dispatch.py`, `sstack_route.py`, `sstack_doctor.py`, `sstack_ui.py`, `sstack_lessons.py`, `sstack_worktree.py` |
| `defaults/` | the built-in config layer: `config.toml`, `harnesses/`, `roles/`, `ades/` |
| `skills/<name>/SKILL.md` | the 13 skills; `skills/sstack/` is the router |
| `ui/` | dashboard front end (`index.html`, `app.js`, `pages/*.js`, `tokens.css`) |
| `docs/spec/` | contracts: `config.md`, `ade.md`, `dispatch.md`, `doctor.md`, `ui.md` |
| `docs/guide/` | these user and agent guides |
| `docs/design.md` | design history and rationale |
| `tests/` | `test_*.py` (stdlib `unittest`), `helpers.py`, `fakes/`, `fixtures/` |

## Run the tests

```sh
python3 -m unittest discover -s tests   # needs: an sstack clone as cwd; about a minute
python3 -m unittest discover -s tests -p test_docs.py   # needs: an sstack clone as cwd
```

Expected: `OK` and exit 0. Each test uses a temporary `HOME` and git repo
(`tests/helpers.py` `TempEnv`). Harness CLIs are replaced by `tests/fakes/fake_agent.py`; ADE CLIs
(`t3`, `orca`, `conductor`) by `tests/fakes/fake_cli.py` through env vars such as
`T3CODE_CLI_PATH`. Never point a test at the real `t3` CLI or at `~/.sstack`.

Run one area while you work:

| area | test file |
|---|---|
| config loader, layers, legacy | `test_config.py`, `test_contracts.py` |
| `sstack-config migrate` / `show` | `test_configcli.py` |
| ADE detection, hooks | `test_ade.py` |
| dispatch, record, run dir | `test_dispatch.py`, `test_route.py`, `test_integration.py` |
| doctor, smoke | `test_doctor.py` |
| dashboard | `test_ui.py` |
| skills lint | `test_skills.py` |
| these guides | `test_docs.py` |

Use `python3 -m unittest discover -s tests -p <file>` for one file.

## How the docs are tested

`tests/test_docs.py` checks every page in `docs/guide/`:

- the page is linked from `README.md`, and `AGENTS.md` links `docs/guide/`;
- it has `## What this is`, at least one `sh` block, and `## How to change this`; no HTML;
- every relative link and `#anchor` resolves;
- every flag belongs to its command: a flag after an `sstack-*` command (in a block, or in the same
  backticked span) must be in that command's help output, or its subcommand's, or follow that
  command in its own `docs/spec/` file; a flag elsewhere in the prose or a table is checked against
  the page's main command (`PAGE_CMD` in the test). Whole flags only, so a prefix of a real flag fails;
- every `sh` block runs in a fresh sandbox: a temp `HOME`, a git repo with one empty commit as the
  cwd, fake `pi`, `claude`, `codex`, `cursor-agent` first on `PATH`, and `$HOME/sstack` pointing at
  this checkout (it stands in for the `git clone` line). `SSTACK_HOME`, `TMPDIR` and the ADE env vars
  (`T3CODE_*`, `ORCA_AGENT_SESSION_ID`, `CONDUCTOR_SESSION_ID`, `SSTACK_ADE`) are unset, and sstack's
  `bin/` is not on `PATH`. The fakes echo the brief, or answer a smoke canary.

Block conventions:

- The page's setup is the first `sh` block under `## Before you start` (`## Install` on
  getting-started.md). It runs before every other block on the page, so it must put sstack on
  `PATH` (`export PATH="$HOME/sstack/bin:$PATH"`). Each block otherwise runs on its own and must set
  up what it uses.
- Use `${SSTACK_HOME:-$HOME/.sstack}` for the home layer and `mktemp -d` (or `${TMPDIR:-/tmp}`) for
  scratch files outside the repo.
- Commands run one by one; the block fails on the first exit code that differs from the doc:

```sh
sstack-doctor                              # expected exit 0 (the default)
sstack-dispatch plan --brief /dev/null --report /dev/null   # exit 3
git clone https://example.invalid/x.git    # needs: network (not run)
```

- A `text` block right after a command block (prose between is fine) whose first line is
  `# expect` is checked: each following line must match a stdout line, in order, after the test
  writes paths as `<sstack>`, `<repo>` and `<home>` and run-dir stamps as `YYYYMMDD-HHMM`. `…` matches
  anything. Any other `text` block is for readers only:

```text
# expect
PASS config loads: config and ADEs parse
PASS roles resolve: …
```

## Rules

- **Spec first.** A change to a contract (config layout, ADE TOML or hook JSON, dispatch exit codes,
  payloads, `record`, doctor checks, dashboard API) starts with an edit to the matching
  `docs/spec/*.md`. Where the code and a spec differ, the spec wins.
- **Fixtures are frozen.** Files under `tests/fixtures/` are the contract's examples. Don't edit
  them to make a test pass. Add a new case dir (`tests/fixtures/config/<case>/`,
  `tests/fixtures/ades/<case>/`, `tests/fixtures/payloads/<name>.json`) for new behaviour.
- **Stdlib only.** No third-party packages in `lib/`, `bin/` or `tests/`.
- **Skills stay ADE-neutral.** Only `defaults/ades/*.md` may name ADE tools (`delegate_task`,
  `preview_*`, `t3 thread …`); only the router `skills/sstack/SKILL.md` may name `sstack-dispatch`.
  `test_skills.py` enforces both, plus frontmatter and length caps (150 lines per skill, 200 for the
  router). Skill text follows the writing-great-skills guidance: short, imperative, one procedure
  per skill.
- **Docs follow code.** A user-visible change updates the page in `docs/guide/` that covers it, and
  `test_docs.py` must pass.

## Send a change

```sh
git switch -c my-change            # needs: an sstack clone as cwd
python3 -m unittest discover -s tests   # needs: an sstack clone as cwd
git push -u origin my-change       # needs: network and push access
```

- Branch from `main`; never commit to `main` directly.
- One PR per concern. The full suite must pass.
- PR body: what changed and why, the test output, and the evidence. A change a user can see gets a
  before/after screenshot table (`sstack-pr-media <pr> <files> --edit-body`, which puts it in the PR
  description, never a comment). Any other change gets Mermaid diagrams of the flow before and
  after (config layout, dispatch flow, skill routing).
- Review comes from a different model family than the author's; each finding is checked against
  the current code before acting on it.

## How to change this

- This page: `docs/guide/contributing.md`. The docs checks: `tests/test_docs.py` (stdlib; the sandbox
  setup is the `Sandbox` class, the block parser is `commands()`).
- A new guide page must be added to the `Docs` section of `README.md` and to the page list in
  `test_pages_exist_and_linked` if it is required.
- Tests: `python3 -m unittest discover -s tests -p test_docs.py`.
