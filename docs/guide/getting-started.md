# Getting started

## What this is

sstack is a set of `SKILL.md` skills plus a few stdlib-Python commands in `bin/`. The skills run an
engineering task through gated phases. The commands route each delegated role (scout, implement,
review, …) to a harness CLI and model, check the config, and show a dashboard. This page installs
sstack, checks it, and runs a first dispatch. It takes about five minutes and needs only Python 3.11+
and git.

Every `sh` block on these guide pages runs as written in a scratch repo. Lines marked
`# needs: <thing>` need that thing and are skipped by the docs test. A trailing `# exit N` means the
command is expected to exit with `N`. Commands that start a child agent call your real harness CLI
(`claude`, `pi`, `codex`, `cursor-agent`); the docs test puts fakes in their place.

## Install

```sh
git clone https://github.com/cobeo2004/sstack.git ~/sstack   # needs: network
export PATH="$HOME/sstack/bin:$PATH"                          # so the commands below resolve
python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
sstack-install --dry-run
sstack-install
```

Expected: the dry run prints what it would change and writes nothing. The real run:

- symlinks `skills/*` into each skill dir that already exists: `~/.claude/skills`, `~/.agents/skills`,
  `~/.codex/skills`, `~/.cursor/skills`, `~/.pi/agent/skills`;
- adds one marked line pointing at the `sstack` skill to `~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`
  and `~/.pi/agent/AGENTS.md`;
- creates an empty `~/.sstack/`;
- prints the optional hook snippets (post-edit check, end-of-session reflect) for each harness
  whose skill dir exists; it writes no harness settings. Each harness note in
  `skills/sstack/harness-notes/` has the same snippets.

Output (the dry run, then the real run's first line):

```text
# expect
would create <home>/.sstack/
Optional hooks (sstack writes no harness settings): post-edit runs `check` from .sstack/project.toml;
end-of-session runs reflect when [reflect] auto = true in ~/.sstack/config.toml.
No harness skill dir found; hook snippets: <sstack>/skills/sstack/harness-notes/
create <home>/.sstack/
```

A skill already installed under the same name is renamed to `<name>.bak`, never deleted.
`sstack-install --uninstall` removes only sstack's own symlinks and the marked line. Restart your
agent afterwards so it loads the skills.

## Check the install

```sh
sstack-doctor
```

Expected (exit 0 when every line is `PASS`):

```text
# expect
PASS config loads: config and ADEs parse
PASS no legacy files: none
PASS roles resolve: implement → pi/opencode-go/deepseek-v4.1-flash; review → codex/gpt-6.1-sol, claude/opus; scout → claude/haiku
PASS harness CLIs: claude, codex, pi
PASS active ADE: name None, why no adapter detected, delegate None, browser None, device None, capture None, note None
PASS hooks executable: ok
```

`FAIL harness CLIs` names the agent CLIs missing from `PATH`. `FAIL no legacy files` means an old
single-file config: see [Migrate an old config](configuration.md#migrate-an-old-config). Every check
is described in [doctor.md](doctor.md).

## See where each role goes

```sh
sstack-dispatch scout --brief /dev/null --report /dev/null --dry-run
sstack-dispatch implement --brief /dev/null --report /dev/null --dry-run
sstack-dispatch plan --brief /dev/null --report /dev/null --dry-run   # exit 3
```

Expected with the built-in defaults, outside any ADE:

```text
# expect
route: role default
ade: None (no adapter detected)
headless: claude -p --model haiku --permission-mode plan
route: role default
ade: None (no adapter detected)
headless: pi -p --no-session --model opencode-go/deepseek-v4.1-flash --thinking high
local
```

`local` with exit 3 is not an error: that role has no config, so your own session does the work.

## Run a first dispatch

```sh
printf 'List the files in this repo.\n' > brief.md
sstack-dispatch scout --brief brief.md --report scout.md --title "first scout"
cat scout.md
tail -n 1 .sstack/runs/index.jsonl
```

Expected: exit 0, the scout's answer in `scout.md`, and one JSON line in
`.sstack/runs/index.jsonl` with `"role": "scout"`, `"exit": 0` and `"via": "headless"`. Inside an
ADE such as T3 Code the same command exits 4 instead and prints a tool payload; see
[dispatch.md](dispatch.md#exit-4-make-the-tool-calls).

## Set up a repo

Open the repo in your agent and say "set up this repo". The `setup` skill audits the repo and the
machine read-only, shows a table of recommended changes — `.sstack/product.md`,
`.sstack/project.toml` with the verify commands, the code graph, one `AGENTS.md` row — and writes
only the rows you pick. It then asks before running the smoke test
([doctor.md](doctor.md#run-the-smoke-test)).

`check` in `.sstack/project.toml` is a fast check of one file (`{path}` = the edited file, e.g.
`ruff check {path}`); the post-edit hook runs it after each agent edit and feeds a failure back.
Edits made through the shell fire no hook, so run the same `check` in CI too. Contract:
[docs/spec/hooks.md](../spec/hooks.md).

## Next

- [configuration.md](configuration.md): the split config and its four layers.
- [ades.md](ades.md): how sstack detects T3 Code, Orca, Conductor and Cursor.
- [dispatch.md](dispatch.md): roles, panels, exit codes and run records.
- [dashboard.md](dashboard.md): the local config and runs cockpit.

## How to change this

- Installer: `bin/sstack-install`; tested by `tests/test_install.py`. Hook snippets live in its
  `HOOKS` and in each harness note; keep both in step.
- Built-in roles and harnesses that the output above shows: `defaults/roles/*.toml`,
  `defaults/harnesses/*.toml` (contract: [docs/spec/config.md](../spec/config.md)).
- If you change a default, update the expected output on this page and run
  `python3 -m unittest discover -s tests -p test_docs.py`.
