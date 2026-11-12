# Config layout and loader — contract

Owner: `lib/sstack_config.py`. Fixtures: `tests/fixtures/config/<case>/` (each with
`expected.json` = `load()` output). Checked by `tests/test_contracts.py`, `tests/test_config.py`.

## Layout (one file per thing)

```
<layer>/
  config.toml            ade, [dispatch], [rules], [reflect], [routing], [overnight], [unattended] — merged key by key
  project.toml           repo layers only (repo, local); replaced whole      — was [project]
  harnesses/<name>.toml  one harness                                         — replaced whole
  roles/<role>.toml      one role (sub-tables like [hint.ui] allowed)        — replaced whole
  roles/<stage>/<name>.toml  a stage variant (investigate, plan, review)     — replaced whole
  roles/<stage>/<name>.md    the variant's lens, appended to its brief       — per file
  tiers/<tier>.toml      one tier                                            — replaced whole
  ades/<name>.toml       one ADE adapter (docs/spec/ade.md)                  — replaced whole
  ades/<name>.hook       optional executable; ades/<name>.md optional note   — per file
  steps/<name>/step.toml one workflow step (docs/spec/workflow.md)           — merged key by key
  steps/<name>/brief.md  a role step's brief                                 — per file, nearest wins
  steps/<name>/run.sh    a command step's executable                         — per file, nearest wins
```

A file's top level is the table itself: `roles/implement.toml` holds `harness = "pi"`, not
`[role.implement]`.

`project.toml` keys are read by skills (template: `skills/setup/templates/project.toml`), except
`check`, `verify` and `protected`: `check` is a fast file-scoped shell command with a `{path}`
placeholder, run by `sstack-hook post-edit` on each edited file ([hooks.md](hooks.md)); `verify` and
`protected` are read by `sstack-gate` ([gate.md](gate.md)). Unset or empty → no check / no commands /
no protected globs beyond `.sstack/project.toml`.

`verify` is a string or a list of strings, run with `sh -c` in the repo root, in order. The gate
reads the base branch's copy; `protected` is a list of globs where a modified or deleted file fails.
`.sstack/project.toml` is always protected. A new file under a protected glob passes.

```toml
# project.toml
verify = ["pnpm lint", "pnpm test"]  # string or list; the base branch's copy is authoritative
protected = ["lib/core/*"]           # modified/deleted files fail; .sstack/project.toml is implicit
check = "ruff check {path}"          # fast single-file check, run by the post-edit hook
```

```toml
# config.toml
ade = "auto"              # auto | none | <adapter>; env SSTACK_ADE wins
[dispatch]
via = "auto"              # auto | headless | local | ade-cli   (docs/spec/dispatch.md)
timeout_min = 30
[rules]
review_not_implementer = true
max_parallel = 4
auto_escalate = true
tier_order = ["cheap", "standard", "strong"]
panel_diff_lines = 400
[reflect]
auto = false
encode_at = 2
# [routing.kinds] frontend = "ui-fast"
# [skills.kinds] backend = ["py-style"]   # skills for a work kind (docs/spec/dispatch.md#skills)
```

Skill keys (R19–R21; read by `lib/sstack_skills.py`, never validated by the loader):

| file | key | meaning |
|---|---|---|
| `roles/<role>.toml` | `skills = []` | skill names every child of the role uses; none by default |
| `config.toml` | `[skills.kinds] <kind> = []` | skill names for a work kind (built-in or `[routing.kinds]`) |
| `project.toml` | `[practices] "<glob>" = []` | for `--files` matching the glob: skill names, or doc paths / URLs (any entry with a `/` or ending `.md`) passed through as "read" links |
| `harnesses/<h>.toml` | `[session]` | how this harness starts children when it runs the session and no ADE is detected: `detect` env markers, `[session.agent]`, `[session.shell]` (docs/spec/dispatch.md § Session harness); read by dispatch, not validated by the loader (doctor does) |
| `harnesses/<h>.toml` | `skill_dirs = []` | where the harness's skills live (`~` expands; a relative dir is under the repo root; paths handed to children are absolute); replaces the built-in list: claude `~/.claude/skills`, `~/.agents/skills`; codex `~/.codex/skills`, `~/.agents/skills`; cursor `~/.cursor/skills`, `~/.agents/skills`; pi `~/.pi/agent/skills`, `~/.agents/skills`; any other `~/.agents/skills` |

The built-in `skill_dirs` live in code, not in the template's `harnesses/*.toml`, so `load()` output is
unchanged for configs without skill keys. Fixture: `skills-keys`.

## `[overnight]`

The `overnight` skill's policy ([guide](../guide/overnight.md)). `load()` merges it key by key across
the three layers; `sstack-gate --merge` re-reads it with the repo layer pinned to the base branch
([gate.md](gate.md)). No other code reads it.

| key | default | type / values | read by |
|---|---|---|---|
| `merge` | `"never"` | `never` or `policy` | gate, doctor |
| `method` | `"merge"` | `merge`, `squash` or `rebase` | skill |
| `merge_min_score` | `8` | int 1–10 | gate, doctor |
| `max_diff_lines` | `400` | int ≥ 1 | gate, doctor |
| `never_merge` | `[]` | list of globs | gate, doctor |
| `merge_with_assumptions` | `false` | bool | gate, doctor |
| `on_question` | `"decide"` | `decide` or `park` | skill, doctor |
| `on_stuck` | `"draft"` | `draft` or `park` | skill, doctor |
| `stop_at` | `""` | `""` or local `HH:MM` (00:00–23:59) | skill, doctor |

`sstack-doctor`'s `overnight` check FAILs a value outside those ranges and PASSes with `merge never`,
or `merge policy (<method>, score ≥ <n>)` when `merge = "policy"`. The table is part of `load()`
output, so every fixture's `expected.json` carries it.

## `[unattended]`

Unattended mode runs `work` and `setup` with nobody in the thread ([workflow.md](workflow.md#unattended)).
`load()` merges the table across the layers like any `config.toml` table, so a git-ignored
`.sstack/local/config.toml` can turn it on for one checkout. Resolved by `unattended(cfg, env)` in
`lib/sstack_config.py`, shown by `sstack-workflow unattended`.

| key | default | type / values | env |
|---|---|---|---|
| `enabled` | `false` | bool | `SSTACK_UNATTENDED=1` turns it on, as `enabled = true` does |
| `plan_gate` | `"inbox"` | `auto` or `inbox` | `SSTACK_PLAN_GATE` overrides it for one process |

```toml
# .sstack/local/config.toml, as Hive writes it per job
[unattended]
enabled = true
plan_gate = "auto"   # or "inbox"
```

The env beats the config; the config beats the default. Any other `plan_gate` or `SSTACK_PLAN_GATE`
value, or a non-bool `enabled`, is a `ConfigError` naming the allowed values (`auto, inbox`), and
`sstack-doctor`'s `unattended` check FAILs it. The defaults live in code and the template lists the
keys commented out, so `load()` output and `sstack-config sync` are unchanged until a layer sets them.

## Stage variants

A stage variant is an extra member for `investigate`, `plan` or `review`, next to the stage's
default (`roles/<stage>.toml`). `roles/<stage>/<name>.toml` holds:

| key | meaning |
|---|---|
| `harness`, `model`, `effort` or `tier` | the member, as in a role or a `[hint.*]` |
| `panel = [{harness, model}, …]` | a variant panel instead: one member and one report each |
| `paths = ["<glob>"]` | run when a `--files` path matches a glob (`fnmatch`, the path as passed) |
| `kinds = ["backend"]` | run when a `--files` path has that kind (`sstack_route._kind`) |
| `when = "<text>"` | what it is for; shown by `sstack-dispatch routes` |
| `skills = []` | skill names added to this variant's brief only |
| `enabled = false` | switch it off (usually in a nearer layer) |

Matching: a variant runs when any file matches `paths` or `kinds`; with neither it always runs.
Review's files are `--files`, else the detected diff. Each `.toml` and `.md` resolves per file
through the layers, nearest wins, so a `local` `security.toml` with `enabled = false` turns off a
repo variant, and a repo `security.md` re-lenses a home variant. The `.md` is appended to the
variant's brief under `## Lens: <stage>/<name>`; without one the variant runs on the plain brief
(`sstack-doctor` WARNs). There are no `implement` variants: `roles/implement/` is never read and
`sstack-doctor` FAILs on it; route implement with `[hint.*]`. How variants run: docs/spec/dispatch.md.

`[transport]` is gone: `[dispatch] via = "local"` replaces `mode = "local"`, `via = "ade-cli"`
replaces `mode = "thread"`, `[dispatch] timeout_min` replaces transport's. `t3_provider` leaves
harness files for the ADE file's `[providers]`; `[transport.t3]` becomes the ADE file's `[cli]`.

## Layers (lowest first)

| name | dir |
|---|---|
| `home` | `$SSTACK_HOME`, else `~/.sstack` — the profile, created by `sstack-config sync` |
| `repo` | `<git root>/.sstack` |
| `local` | `<git root>/.sstack/local` (git-ignored: one line `.sstack/local/`) |

`repo` and `local` exist only inside a git repo. In a linked worktree each of those two dirs falls
back to the primary checkout's when this checkout's dir holds no config files (it may still hold
`runs/`); the choice is per dir, so a worktree can have its own `local/` over the primary's `.sstack`.
Fixtures: `worktree-fallback` (the worktree's own `local/` wins; the primary's `local/` is not read)
and `worktree-local-fallback` (no `local/` in the worktree → the primary's `local/` is used).

Merge: `load()` folds layers in order. With no `config.toml` in home, `load()` raises
`ConfigError: no sstack profile at <home>: run `sstack-config sync`` (so do dispatch, doctor,
workflow, gate and ui); nothing is read silently from the template. `config.toml` merges key by key (nested tables too);
harness/role/tier/ade files and `project.toml` replace the lower layer's file whole.

Step folders are read by `steps()`, *not* `load()`, so `load()` output is unchanged by them
(`tests/test_contracts.py` snapshots it): `steps/<name>/step.toml` merges key by key across layers,
and `brief.md` / `run.sh` each come whole from the nearest layer that has one. `steps/` counts as a
layer's config for the worktree fallback above, like every other layout entry. Contract:
[workflow.md](workflow.md).

## Legacy

Legacy = a `config.toml` holding any of `[harness.*] [role.*] [tier.*] [project] [transport]`, or a
`.sstack/config.local.toml`. Hard cut: whenever `legacy(root)` is non-empty — even beside split
files — `load()` raises `ConfigError` (fixtures `legacy-only`, `legacy-local`, `mixed-legacy-split`).
`legacy()` lists each file once (home and repo are the same dir when `$HOME` is the git repo).

```
legacy sstack config ~/.sstack/config.toml: run `sstack-config migrate` to split it into the new layout (docs/spec/config.md)
```

## API

```python
load(root: Path | None) -> dict
# {"ade": "auto", "dispatch": {...}, "rules": {...}, "reflect": {...},
#  "harness": {"pi": {...}}, "role": {"scout": {...}}, "tier": {...}, "project": {...}}
layers(root) -> [(name, dir)]            # [("home", …), ("repo", …), ("local", …)]
require_profile(root)                     # ConfigError when home has no config.toml (load() calls it)
trusted(root) -> bool                     # root or its primary is listed in ~/.sstack/repos.txt
source(root, kind, name) -> (layer, path) | None
# kind: config | project | harnesses | roles | tiers | ades | steps; name = file stem, dots allowed
# ("ui.fast") or, for ades, a file name ("t3.md" / "t3.hook"); for roles, a variant "review/security"
# or its lens "review/security.md" (stages investigate | plan | review only); for steps,
# "<name>/step.toml", "<name>/brief.md" or "<name>/run.sh". Only names listed in that dir match.
# e.g. source(root, "roles", "review") -> ("local", <root>/.sstack/local/roles/review.toml)
# A code file (steps "<name>/run.sh", ades "<name>.hook") that no layer has resolves from the
# template: ("template", <sstack>/defaults/steps/gate/run.sh). Any layer's copy wins.
steps(root) -> {name: {"spec": dict, "source": {key or file: layer}, "brief": Path | None,
                       "run": Path | None, "builtin": bool}}
# steps/<name>/ of every layer: step.toml merged per key, brief.md and run.sh each whole from the
# nearest layer (run.sh: else the template's), builtin = ships in the template's steps/. Read
# outside load() (docs/spec/workflow.md).
legacy(root) -> [Path]                   # legacy files, any layer
ades(root) -> [{"name", "layer", "toml", "hook_path" | None, "note_path" | None, "auto"}]
# detection order: local, repo, home; within a layer the user's own ADEs alphabetically, then the
# ones the template ships (synced built-ins) alphabetically; a nearer file shadows a farther one of
# the same name; hook/note resolve per file (nearest layer; a hook then falls back to the template).
variants(root) -> [{"id", "stage", "name", "layer", "path", "spec", "lens_path" | None}]
# enabled stage variants, by stage then name; layer/path = the winning .toml, lens_path = nearest .md
unattended(cfg, env=None) -> {"enabled": bool, "plan_gate": "auto" | "inbox"}   # env defaults to os.environ
resolve(cfg, role) -> [{"harness", "model", "effort"}] | None   # None = run locally
# None when dispatch.via == "local", the role is unset, or every member is harness "local".
```

`ConfigError` messages name the file (`<path>: <toml error>`) or the fix.

## `sstack-config migrate` (B1)

```
sstack-config migrate [--global | --repo] [--dry-run]
```

Default: the home layer and the current repo. `--global`: home only. `--repo`: this repo only.
`--dry-run`: print the plan, write nothing. For each legacy file it writes the split files into the
same layer dir (`.sstack/config.local.toml` → `.sstack/local/`, adding `.sstack/local/` to
`.gitignore`), then renames the file to `<name>.bak` (`config.toml.bak`, `config.local.toml.bak`).
All or nothing: if any target file or `.bak` already exists, nothing is written. Afterwards it runs
`load()` and prints ``next: ask the user, then `sstack-doctor --smoke` ``.

| legacy | becomes |
|---|---|
| `[harness.X]` | `harnesses/X.toml`; `t3_provider` dropped, note: provider ids live in `ades/t3.toml [providers]` |
| `[role.X]` (with sub-tables) | `roles/X.toml` |
| `[tier.X]` | `tiers/X.toml` |
| `[project]` | `project.toml` (repo layers; in home: dropped, note: project is repo-only) |
| `[transport] mode` | `[dispatch] via`: `thread` → `ade-cli`, `auto` → `auto`, `headless` → `headless`, `local` → `local` |
| `[transport] timeout_min` | `[dispatch] timeout_min` (an existing `[dispatch]` value wins) |
| `[transport.t3]` | dropped, note: thread start is `[cli]` in `ades/t3.toml` (sstack-config sync copies the template's) |
| anything else | stays in `config.toml` |

Output: one line per action (`write <path>`, `rename <path> → <path>.bak`, `note: …`). Exit 0 =
migrated, dry run, or nothing to migrate (`no legacy config`); 1 = error (bad TOML, target or
`.bak` exists, `load()` fails afterwards). With no profile afterwards it skips the `load()` check
and prints `note: no sstack profile at <home>: run `sstack-config sync``; migrate first, then sync
(sync refuses a legacy `config.toml`).

## `sstack-config show` (B1)

```
sstack-config show                    # every thing: `<kind>/<name>  <layer>  <path>`, one per line
sstack-config show <kind>/<name>      # roles/review, roles/review/security, harnesses/pi, tiers/strong, ades/t3, ades/t3.md
sstack-config show config | project
sstack-config show steps/<name>/<file>  # steps/gate/run.sh, steps/review/step.toml
```

A whole-file thing prints `# <layer>: <path>` and then the winning file verbatim (`source()`).
`config` prints every layer's `config.toml` that exists, lowest first, each under its own header
(they merge key by key; later wins). Not found in any layer → exit 1, `no <kind>/<name> in any layer`.
A code file no layer has prints `# template: <sstack>/defaults/…`. The bare listing only lists
`*.toml` things. With no profile, `show` exits 1 with the no-profile error.

## The profile template and `sstack-config sync`

`<sstack>/defaults/` is the profile template, not a layer. `sstack-install` runs `sync`; users and
agents then edit `~/.sstack` directly. At runtime the template is read only for code files
(`steps/*/run.sh`, `ades/*.hook`, see `source()`), `steps()`' `builtin`, the ADE sort key, and
sync itself, so a `git pull` delivers fixes to code but never changes a profile value.

```
sstack-config sync [--dry-run]
```

- Files: every template file ending `.toml` or `.md` that home lacks is copied (parent dirs made).
  An existing file or symlink is never overwritten. `run.sh`, `*.hook` and `hooks/pi-sstack.ts`
  are not copied (they resolve from the template).
- Keys, `config.toml` only: with no `config.toml` in home it is a plain copy. A legacy home
  `config.toml` refuses the whole sync (exit 1, the migrate hint), writing nothing. Otherwise each
  template `key = value` line (outside multi-line values) whose full key path home lacks is
  inserted as the template's own line: a root key before home's first table header (or at the
  end), a table key right after home's matching `[header]` line, else a new `[header]` appended at
  the end. The result must parse and equal home's data plus exactly the added values; otherwise
  (a multi-line value, a table home writes inline or with dotted keys) nothing is written to
  `config.toml` and it prints `config.toml: cannot add <keys> automatically; copy them from
  <template>` and exits 1 (missing files are still copied). Existing keys are never rewritten;
  `step.toml` and other files sync per file only.
- Output: `copy <rel>` / `add config.toml <key>` per item (`would …` under `--dry-run`), or
  `profile <home> is in sync with <template>`.

`sstack-doctor`'s first check, `profile`, FAILs without a profile and WARNs `drift: missing <rel>,
missing key config.toml <key>; run sstack-config sync` for what sync would add.

Dashboard HTTP interface: docs/spec/ui.md.
