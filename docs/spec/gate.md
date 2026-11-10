# sstack-gate — contract

Owner: `lib/sstack_gate.py`; entry point: `bin/sstack-gate`. Tests: `tests/test_gate.py`. The exit
code is the verdict: **0 PASS, 1 FAIL, 2 usage or setup error**. A setup error runs nothing and writes
nothing.

## CLI

```
sstack-gate [--run <run-dir>] [--pr]
```

- `--run` writes the verdict and full log into `<run-dir>/gate/`.
- `--pr` also enforces before/after PR evidence from `<run-dir>/media/`; it requires `--run`.
- Without `--run`, the verdict is printed to stdout and no file is written.

The repo must be registered in `$SSTACK_HOME/repos.txt` (or `~/.sstack/repos.txt`). This is the same
trust check the post-edit hook uses: both call `trusted(root)` in `lib/sstack_config.py`. An
unregistered repo exits 2 before `verify`, before a verdict, and before any run file is created.

## Config source

The gate reads the raw `.sstack/project.toml` from `git show <base_ref()>:.sstack/project.toml`. If
the base commit has no such file, it reads the raw working-tree `.sstack/project.toml` and says so in
the verdict. It never merges layers and never reads `.sstack/local/project.toml`.

`verify` is a string or a list of strings. Each command runs with `sh -c` in the repo root, in order.
The first failure stops the remaining commands. A generous per-command timeout (15 minutes) turns a
stuck command into a FAIL. All stdout and stderr go to the full log and its tail goes in the verdict.
`protected` is a list of glob patterns; `.sstack/project.toml` is always protected.

## Diff and protected files

The change set is computed against the merge base:

```
git merge-base <base_ref()> HEAD
git diff --name-status --no-renames <merge-base>
git ls-files --others --exclude-standard
```

The diff is against the working tree, so committed and uncommitted edits are both visible. Untracked
files count as added. Renames appear as a delete plus an add (`--no-renames`).

A **modified or deleted** file matching `protected`, or `.sstack/project.toml`, fails the gate. An
**added** file matching a protected glob passes: the rule protects existing files, not new ones.

## `--run`: protected manifest

`work` Phase 1 writes backups under `<run-dir>/protected/` and a `SHA256SUMS` file beside them in
`shasum -a 256` format, one `<sha256>  <repo-relative-path>` per line. It also writes
`<run-dir>/protected/mode` as `restore` or `strict`; `work` restores in `restore` mode before calling
the gate, so the gate only verifies hashes.

- `protected/` absent or empty → nothing to check.
- Backups present without `SHA256SUMS` → FAIL with the command that writes the manifest.
- A manifest row whose repo file is missing or whose sha256 differs → FAIL naming the path.
- The gate hashes repository files, never the backup files.

## `--pr`: evidence

Each changed file is classified with `sstack_route._kind`. Test files and paths whose kind is `None`
are excluded (D4). A diff that owes nothing passes without media.

| changed kind | at least one required in `<run-dir>/media/` |
|---|---|
| `frontend`, `mobile` | `after-<key>.<image-or-video>`: `.png .jpg .jpeg .gif .webp .mp4 .mov .webm` |
| `backend`, `security` | `after-<key>.mmd` |

A `.mmd` is required for a backend/security diagram. Archify `.png`/`.svg` files are extras: they never
replace the `.mmd`, and `.svg` never counts as the frontend/mobile image.

Every `after-<key>` needs a `before-<key>` of the same kind (visual or diagram). `media/no-before.md`
waives a missing before and its reason is quoted in the verdict. `media/skip.md` waives the whole
evidence check: the verdict is PASS with `MEDIA WAIVED: <reason>` in the summary, while the normal
`verify` and protected checks still run.

## Verdict and log

With `--run`, `<n>` starts at 1 and increments across all gate calls in that run:

| call | verdict | log |
|---|---|---|
| normal | `<run-dir>/gate/<n>.md` | `<run-dir>/gate/<n>.log` |
| `--pr` | `<run-dir>/gate/<n>-pr.md` | `<run-dir>/gate/<n>-pr.log` |

The verdict starts with `GATE: PASS` or `GATE: FAIL`, has `## Summary` with 3–5 bullets, lists every
failure under `## Details`, and ends with the log tail under `## Log`. A no-run verdict is the same
text on stdout.

The gate still runs `verify` after a protected-file failure, and still checks the manifest and
evidence after any failure, so one verdict names everything that needs fixing.
