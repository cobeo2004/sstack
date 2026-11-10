# Config layout and loader — contract

Owner: `lib/sstack_config.py`. Fixtures: `tests/fixtures/config/<case>/` (each with
`expected.json` = `load()` output). Checked by `tests/test_contracts.py`, `tests/test_config.py`.

## Layout (one file per thing)

```
<layer>/
  config.toml            ade, [dispatch], [rules], [reflect], [routing]   — merged key by key
  project.toml           repo layers only (repo, local); replaced whole      — was [project]
  harnesses/<name>.toml  one harness                                         — replaced whole
  roles/<role>.toml      one role (sub-tables like [hint.ui] allowed)        — replaced whole
  tiers/<tier>.toml      one tier                                            — replaced whole
  ades/<name>.toml       one ADE adapter (docs/spec/ade.md)                  — replaced whole
  ades/<name>.hook       optional executable; ades/<name>.md optional note   — per file
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
| `harnesses/<h>.toml` | `skill_dirs = []` | where the harness's skills live (`~` expands; a relative dir is under the repo root; paths handed to children are absolute); replaces the built-in list: claude `~/.claude/skills`, `~/.agents/skills`; codex `~/.codex/skills`, `~/.agents/skills`; cursor `~/.cursor/skills`, `~/.agents/skills`; pi `~/.pi/agent/skills`, `~/.agents/skills`; any other `~/.agents/skills` |

The built-in `skill_dirs` live in code, not in `defaults/harnesses/*.toml`, so `load()` output is
unchanged for configs without skill keys. Fixture: `skills-keys`.

`[transport]` is gone: `[dispatch] via = "local"` replaces `mode = "local"`, `via = "ade-cli"`
replaces `mode = "thread"`, `[dispatch] timeout_min` replaces transport's. `t3_provider` leaves
harness files for the ADE file's `[providers]`; `[transport.t3]` becomes the ADE file's `[cli]`.

## Layers (lowest first)

| name | dir |
|---|---|
| `defaults` | `<sstack>/defaults/` — ships harnesses pi/codex/claude/cursor, roles scout/implement/review, built-in ADEs; **no tiers** (kind routing off) |
| `home` | `$SSTACK_HOME`, else `~/.sstack` |
| `repo` | `<git root>/.sstack` |
| `local` | `<git root>/.sstack/local` (git-ignored: one line `.sstack/local/`) |

`repo` and `local` exist only inside a git repo. In a linked worktree each of those two dirs falls
back to the primary checkout's when this checkout's dir holds no config files (it may still hold
`runs/`); the choice is per dir, so a worktree can have its own `local/` over the primary's `.sstack`.
Fixtures: `worktree-fallback` (the worktree's own `local/` wins; the primary's `local/` is not read)
and `worktree-local-fallback` (no `local/` in the worktree → the primary's `local/` is used).

Merge: `load()` folds layers in order. `config.toml` merges key by key (nested tables too);
harness/role/tier/ade files and `project.toml` replace the lower layer's file whole.

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
layers(root) -> [(name, dir)]            # [("defaults", …), ("home", …), ("repo", …), ("local", …)]
trusted(root) -> bool                     # root or its primary is listed in ~/.sstack/repos.txt
source(root, kind, name) -> (layer, path) | None
# kind: config | project | harnesses | roles | tiers | ades; name = file stem, dots allowed ("ui.fast")
# or, for ades, a file name ("t3.md" / "t3.hook"). Only names listed in that dir match (no "../").
# e.g. source(root, "roles", "review") -> ("local", <root>/.sstack/local/roles/review.toml)
legacy(root) -> [Path]                   # legacy files, any layer
ades(root) -> [{"name", "layer", "toml", "hook_path" | None, "note_path" | None, "auto"}]
# detection order: local, repo, home (alphabetical within each), then defaults (alphabetical);
# a user file shadows the built-in of the same name; hook/note resolve per file (nearest layer).
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
| `[transport.t3]` | dropped, note: thread start is `[cli]` in `defaults/ades/t3.toml`; override with `ades/t3.toml` |
| anything else | stays in `config.toml` |

Output: one line per action (`write <path>`, `rename <path> → <path>.bak`, `note: …`). Exit 0 =
migrated, dry run, or nothing to migrate (`no legacy config`); 1 = error (bad TOML, target or
`.bak` exists, `load()` fails afterwards).

## `sstack-config show` (B1)

```
sstack-config show                    # every thing: `<kind>/<name>  <layer>  <path>`, one per line
sstack-config show <kind>/<name>      # roles/review, harnesses/pi, tiers/strong, ades/t3, ades/t3.md
sstack-config show config | project
```

A whole-file thing prints `# <layer>: <path>` and then the winning file verbatim (`source()`).
`config` prints every layer's `config.toml` that exists, lowest first, each under its own header
(they merge key by key; later wins). Not found in any layer → exit 1, `no <kind>/<name> in any layer`.

Dashboard HTTP interface: docs/spec/ui.md.
