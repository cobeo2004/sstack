# Configuration

## What this is

sstack config is split into one small TOML file per thing (a role, a harness, a tier, an ADE) and
stacked in three layers: your home profile, the repo, and a personal git-ignored layer inside the
repo. A later layer wins. The home profile starts as a copy of sstack's template (`<sstack>/defaults/`),
made by `sstack-config sync`; edit `~/.sstack` directly. `sstack-config show` prints the effective file and the layer it
came from; `sstack-config migrate` converts an old single-file config. The full contract is
[docs/spec/config.md](../spec/config.md); this page shows how to use it.

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
sstack-config sync >/dev/null          # your ~/.sstack profile, as sstack-install creates it
```

## Layout

Every layer dir may hold any of these. A file's top level is the table itself:
`roles/implement.toml` holds `harness = "pi"`, not `[role.implement]`.

| path | holds | merge |
|---|---|---|
| `config.toml` | `ade`, `[dispatch]`, `[rules]`, `[reflect]`, `[routing]`, `[overnight]` | key by key, nested tables too |
| `project.toml` | repo facts: `verify`, `protected`, `[test.<surface>]`, `graph` (repo and local layers only) | replaced whole |
| `harnesses/<name>.toml` | `headless`, `headless_readonly` argv templates; optional `session_kind` with `session_id_args` or `session_events_args` (built in for `claude` and `codex`: [spec](../spec/dispatch.md#headless-session-capture)); optional `[session]` ([ades.md](ades.md#session-harness-no-ade)) | replaced whole |
| `roles/<role>.toml` | `harness`, `model`, `effort`, `mode`, `panel`, `[hint.<name>]` | replaced whole |
| `roles/<stage>/<name>.toml` | a stage variant for `investigate`, `plan` or `review` ([below](#add-a-stage-variant)) | replaced whole |
| `roles/<stage>/<name>.md` | that variant's lens | nearest layer per file |
| `tiers/<tier>.toml` | `harness`, `model`, `effort` | replaced whole |
| `ades/<name>.toml` | one ADE adapter ([ades.md](ades.md)) | replaced whole |
| `ades/<name>.hook`, `ades/<name>.md` | optional hook and agent note | nearest layer per file |
| `steps/<name>/step.toml` | one workflow step: `after`, `role`, `gate`, `on_fail`, `max_loops`, `max_agents`, `min_score`, `enabled` ([workflow.md](workflow.md)) | key by key |
| `steps/<name>/brief.md`, `steps/<name>/run.sh` | a step's brief (role step) or command (command step) | nearest layer per file |

`config.toml` keys and their template values (`defaults/config.toml`):

```toml
ade = "auto"              # auto | none | <adapter name>; env SSTACK_ADE wins
[dispatch]
via = "auto"              # auto | headless | local | ade-cli (dispatch.md)
timeout_min = 30
[rules]
review_not_implementer = true   # drop any panel member equal to the implement role's model
max_parallel = 4
loop_guard = 2
auto_escalate = true            # a failed child is retried once, one tier up
tier_order = ["cheap", "standard", "strong"]
panel_diff_lines = 400          # a review diff bigger than this gets the full panel
[reflect]
auto = false
encode_at = 2
# [routing.kinds] frontend = "ui-fast"   # remap a built-in work kind to your tier
[overnight]                      # policy for `sstack-gate --merge` (overnight.md)
merge = "never"                  # never | policy
method = "merge"                 # merge | squash | rebase
merge_min_score = 8              # 1..10
max_diff_lines = 400             # additions + deletions
never_merge = []                 # globs; a PR touching one is never merged
merge_with_assumptions = false   # true: merge a run that decided assumptions
on_question = "decide"           # decide | park
on_stuck = "draft"               # draft | park
stop_at = ""                     # "" or local HH:MM; no run starts after it
```

## File schemas

```toml
# harnesses/<name>.toml — argv templates; a placeholder whose value is unset is dropped with its flag
headless = ["pi", "-p", "--no-session", "--model", "{model}", "--thinking", "{effort}"]
headless_readonly = ["pi", "-p", "--no-session", "--model", "{model}", "--tools", "read,grep,find,ls"]

# roles/<role>.toml — one member
harness = "pi"                       # a harnesses/<name>.toml, or "local" (run in-session)
model = "opencode-go/deepseek-v4.1-flash"
effort = "high"                      # optional
[hint.ui]                            # optional override: --hint ui, or --files matching paths
when = "our web app"                 # shown by `sstack-dispatch routes`
paths = ["web/*"]
harness = "claude"
model = "opus"                       # or: tier = "strong"

# roles/review.toml — a panel
mode = "auto"                        # auto | single | panel
panel = [
  { harness = "codex",  model = "gpt-6.1-sol", effort = "high" },
  { harness = "claude", model = "opus" },
]

# tiers/<tier>.toml
harness = "codex"
model = "gpt-6.1-sol"
```

`project.toml` holds the repo's `verify` commands, `protected` globs, `graph`, and one
`[test.<surface>]` table per surface (`code`, `browser`, `mobile`) with the framework, where tests
live, and the run, serve or build commands. `verify` is the base branch's copy of the commands the
[gate](gate.md) runs; `protected` names files the gate refuses to see modified or deleted. `setup`
writes it; [skills/work/testing.md](../../skills/work/testing.md) defines how each surface is tested.

```toml
# project.toml
verify = ["pnpm lint", "pnpm test"]  # string or list; base branch copy wins
protected = ["lib/core/*"]           # .sstack/project.toml is always protected
```

Skills a dispatched child must use: `skills = [...]` in `roles/<role>.toml`, `[skills.kinds]
<kind> = [...]` in `config.toml`, and `[practices] "<glob>" = [...]` in `project.toml` (skill names,
or doc paths / URLs). A harness file's `skill_dirs` overrides where that harness's skills are found.
Missing skills warn, never fail; `sstack-doctor` lists them. Details: [dispatch](dispatch.md#skills-in-the-brief).

## Layers

Lowest first. A later layer wins.

| layer | dir | notes |
|---|---|---|
| `home` | `$SSTACK_HOME`, else `~/.sstack/` | your profile: machine-wide settings, created from the template by `sstack-config sync` |
| `repo` | `<git root>/.sstack/` | committed with the repo |
| `local` | `<git root>/.sstack/local/` | personal; add the line `.sstack/local/` to `.gitignore` |

`repo` and `local` exist only inside a git repo.

## The template and `sstack-config sync`

`<sstack>/defaults/` is the template, not a layer: it ships harnesses `pi`, `codex`, `claude`,
`cursor`; roles `scout`, `investigate`, `plan`, `implement`, `review`; ADEs `t3`, `orca`,
`conductor`, `cursor`; the steps `recon`, `plan`, `implement`, `gate`, `review`, `pr`; no tiers.
`sstack-install` runs `sstack-config sync`, which copies every template `.toml` and `.md` file your
home lacks and adds `config.toml` keys it lacks. It never overwrites a file or a key, so run it
again after a `git pull` to pick up new settings; `--dry-run` lists what it would do:

```sh
sstack-config sync --dry-run
```

With no profile, every command stops with `no sstack profile at <home>: run `sstack-config sync``.
Code files (`steps/*/run.sh`, `ades/*.hook`) are not copied: they come from the template until a
layer has its own. `sstack-doctor` WARNs `drift` when sync has something to add. A harness file you already have is
not rewritten, so one that predates the `[session]` table lacks it: bare Claude Code then
dispatches headless, and doctor WARNs `session harness`. Copy the table from the template.

`steps/` is the workflow: one folder per step, merged per key across the three layers,
so a repo can add, reorder, disable or re-gate a step without touching a skill. What
the keys mean and a worked custom step: [workflow.md](workflow.md).

**Worktree fallback.** In a linked git worktree, each of `.sstack/` and `.sstack/local/` falls back to
the primary checkout's dir when the worktree's own dir holds no config files (a `runs/` dir alone
does not count). The choice is made per dir: a worktree with its own `local/` still reads the
primary's `.sstack/`.

## Show the effective config

```sh
sstack-config show
sstack-config show roles/review
sstack-config show config
sstack-config show tiers/strong   # exit 1
```

`show` with no argument prints one line per thing, `<kind>/<name>  <layer>  <path>`:

```text
# expect
harnesses/claude  home  <home>/.sstack/harnesses/claude.toml
roles/review  home  <home>/.sstack/roles/review.toml
ades/t3  home  <home>/.sstack/ades/t3.toml
```

`show <kind>/<name>` prints `# <layer>: <path>` then the winning file verbatim. `show config` prints
every layer's `config.toml` that exists, lowest first, each under its own header. A thing in no
layer prints `no tiers/strong in any layer` and exits 1. Valid kinds: `config`, `project`,
`harnesses/<n>`, `roles/<n>`, `tiers/<n>`, `ades/<n>` (also `ades/<n>.md`, `ades/<n>.hook`).

## Override a role

Put the file in the layer you want. This makes `implement` use claude for this repo only:

```sh
mkdir -p .sstack/roles
printf 'harness = "claude"\nmodel = "sonnet"\n' > .sstack/roles/implement.toml
sstack-config show roles/implement
sstack-dispatch implement --brief /dev/null --report /dev/null --dry-run
```

Expected:

```text
# expect
# repo: <repo>/.sstack/roles/implement.toml
harness = "claude"
model = "sonnet"
route: role default
ade: None (no adapter detected)
headless: claude -p --model sonnet --permission-mode acceptEdits
```

To return to the inherited file, delete the layer file (`rm .sstack/roles/implement.toml`).

## Add a stage variant

A stage variant is an extra member for `investigate`, `plan` or `review` that runs beside the
stage's default, with its own lens (focus) and its own report. This adds a security reviewer for
auth code in this repo:

```sh
mkdir -p .sstack/roles/review
printf 'harness = "claude"\nmodel = "opus"\nwhen = "auth changes"\npaths = ["auth/*"]\n' \
  > .sstack/roles/review/security.toml
printf 'Look only for authentication and authorisation flaws.\n' > .sstack/roles/review/security.md
sstack-config show roles/review/security
```

Expected:

```text
# expect
# repo: <repo>/.sstack/roles/review/security.toml
harness = "claude"
model = "opus"
when = "auth changes"
paths = ["auth/*"]
```

Keys: the member (`harness`/`model`/`effort`, or `tier`), or `panel = [...]`; `paths` (globs on
the files the work touches) and `kinds` (work kinds like `backend`) choose when it runs, and with neither it always
runs; `when` is a label for the routes listing; `skills` adds skills to its brief only. The
`.md` is appended to its brief under `## Lens: review/security`. Each file resolves on its own, so
`printf 'enabled = false\n' > .sstack/local/roles/review/security.toml` turns it off for you only,
and a nearer `.md` re-lenses a variant defined in your home layer. There are no implement
variants: route implement with `[hint.*]` (`sstack-doctor` fails on a `roles/implement/` folder).
What dispatch does with variants: [dispatch.md](dispatch.md#stage-variants).

## Turn on kind routing with tiers

No tiers ship, so routing by work kind is off. Add tier files in any layer:

```sh
home="${SSTACK_HOME:-$HOME/.sstack}"   # your home layer
mkdir -p "$home/tiers"
printf 'harness = "codex"\nmodel = "gpt-6.1-sol"\n' > "$home/tiers/strong.toml"
printf 'harness = "pi"\nmodel = "opencode-go/deepseek-v4.1-flash"\n' > "$home/tiers/cheap.toml"
sstack-dispatch implement --brief /dev/null --report /dev/null --hint complex --dry-run
sstack-dispatch routes
```

Expected (abridged):

```text
# expect
route: hint complex → tier.strong
headless: codex exec --sandbox workspace-write -m gpt-6.1-sol -
tiers:
  tier.cheap → pi/opencode-go/deepseek-v4.1-flash
  tier.strong → codex/gpt-6.1-sol
escalation: cheap → standard → strong
```

The dry run (`sstack-dispatch implement … --hint complex`) picks `tier.strong`. `sstack-dispatch routes` lists the tiers, the escalation ladder from
`[rules] tier_order` and the built-in kinds: `security`, `complex` → `strong`; `frontend`,
`backend`, `mobile` → `standard`; `mechanical`, `docs` → `cheap`. A built-in kind whose tier is
not defined (here `standard`) falls back to the role's own file. A config hint or a
`[routing.kinds]` remap that names an undefined tier is a config error.

## Migrate an old config

Legacy config is a `config.toml` holding any of `[harness.*]`, `[role.*]`, `[tier.*]`, `[project]`,
`[transport]`, or a `.sstack/config.local.toml`. While one exists, every command fails with:

```text
legacy sstack config ~/.sstack/config.toml: run `sstack-config migrate` to split it into the new layout (docs/spec/config.md)
```

```sh
export SSTACK_HOME="$HOME/old-sstack"   # stands in for an old install: one legacy file, no profile
home="$SSTACK_HOME"
mkdir -p "$home"
printf '[transport]\nmode = "thread"\n\n[role.scout]\nharness = "pi"\nmodel = "small"\n' > "$home/config.toml"
sstack-doctor                        # exit 1
sstack-config migrate --dry-run
sstack-config migrate --global
ls "$home"
sstack-config migrate                # nothing left to do
```

Expected: `sstack-doctor` prints `FAIL no legacy files: … run sstack-config migrate`. The dry run
prints the plan and writes nothing. The real run prints one line per action:

```text
# expect
write <home>/old-sstack/roles/scout.toml
rename <home>/old-sstack/config.toml → <home>/old-sstack/config.toml.bak
write <home>/old-sstack/config.toml
next: ask the user, then `sstack-doctor --smoke`
```

`ls` then shows `config.toml`, `config.toml.bak` and `roles/`. A second `migrate` prints
`no legacy config` and exits 0.

Flags: no flag = home and the current repo; `--global` = home only; `--repo` = this repo only;
`--dry-run` = print, write nothing. It is all or nothing: if any target file or `.bak` already
exists, nothing is written and it exits 1. What each legacy table becomes is in the table in
[docs/spec/config.md](../spec/config.md#sstack-config-migrate-b1). Note that
`[transport] mode = "thread"` becomes `[dispatch] via = "ade-cli"`, which runs the active ADE's
`[cli] cmd`. Only an adapter with a `[cli]` table can do that; the built-in `t3` has one (a new
top-level T3 thread). Under any other ADE, or none, dispatch fails with `dispatch.via = ade-cli but
the active ADE (…) has no [cli] cmd` and exits 1; set `via = "auto"` there instead. After a migrate, ask the user,
then run the smoke test ([doctor.md](doctor.md#run-the-smoke-test)).

## How to change this

- Loader: `lib/sstack_config.py` (`load`, `layers`, `source`, `steps`, `legacy`, `ades`, `resolve`).
- `sstack-config` CLI: `lib/sstack_configcli.py`, `bin/sstack-config`.
- Template values: `defaults/config.toml`, `defaults/roles/`, `defaults/harnesses/`; sync is
  `sync()` in `lib/sstack_configcli.py`.
- Spec first: change [docs/spec/config.md](../spec/config.md), then add a new fixture case under
  `tests/fixtures/config/<case>/` with its `expected.json` (existing fixtures are frozen), then the
  code.
- Tests: `python3 -m unittest discover -s tests -p 'test_config*.py'`,
  `python3 -m unittest discover -s tests -p test_contracts.py`, then this page's check,
  `python3 -m unittest discover -s tests -p test_docs.py`.
