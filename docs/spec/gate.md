# sstack-gate — contract

Owner: `lib/sstack_gate.py`; entry point: `bin/sstack-gate`. Tests: `tests/test_gate.py`. The exit
code is the verdict: **0 PASS, 1 FAIL, 2 usage or setup error**. A setup error runs nothing and writes
nothing.

## CLI

```
sstack-gate [--run <run-dir>] [--pr] [--merge <pr>]
```

- `--run` writes the verdict and full log into `<run-dir>/gate/`.
- `--pr` also enforces before/after PR evidence from `<run-dir>/media/`; it requires `--run`.
- `--merge <pr>` prints a merge verdict for one PR against the `[overnight]` policy; it requires
  `--run` and cannot be combined with `--pr`.
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

## `--merge`: merge verdict

`sstack-gate --merge <pr> --run <run-dir>` decides whether `overnight` may merge one PR. Exit 0
prints `MERGE`; exit 1 prints `HOLD: <reason>; <reason>`; exit 2 is a setup error (no `gh`, a failed
`gh` call, malformed JSON, or a repo missing from `repos.txt`) and nothing is written. The first
stdout line is the verdict, followed by `## Summary` and, on a hold, `## HOLD`.

The policy is the effective `[overnight]` table of `config.toml`, layered defaults → home → repo →
local, with one difference from `load()`: the repo layer is `git show <base_ref()>:.sstack/config.toml`.
When the base has no such file, the working-tree repo file is used if `HEAD` does not track
`.sstack/config.toml`; a tracked-but-absent file is ignored. Either case is named on the verdict's
`- Policy:` line. The local layer is read because it never reaches a PR, unless anything under
`.sstack/local` is tracked in git or `.sstack` or `.sstack/local` is a symlink; then it is ignored and
labelled.

One `gh pr view <pr> --json headRefOid,isDraft,mergeable,baseRefName,statusCheckRollup,additions,deletions,files`
call supplies the PR facts. `HOLD` reasons are collected in this order, and every reason is listed:

| check | hold when |
|---|---|
| policy | `merge` is not `"policy"` |
| gate | the run has no `<run-dir>/gate/<n>-pr.md`, or the highest `n` does not start `GATE: PASS` |
| head | that verdict's `- Head: <sha>` line is missing, says `(dirty)`, or differs from `headRefOid` |
| review | `<run-dir>/workflow.json` `steps.review.status` is not `pass`, or `steps.review.patch` is missing or differs from `fingerprint(headRefOid)`: sha256 of `git diff-tree -p --no-renames <merge-base> <headRefOid>^{tree}` without its `index` lines |
| score | `steps.review.score` is below `merge_min_score` |
| CI | `ci: failed` if a `COMPLETED` check run's conclusion is not `SUCCESS`/`NEUTRAL`/`SKIPPED` or a status context is not `SUCCESS`/`PENDING`/`EXPECTED`; else `ci: pending` if any check is unfinished; an empty rollup is green |
| conflicts | `mergeable` is not `MERGEABLE` |
| diff | `additions + deletions` exceeds `max_diff_lines` |
| `never_merge` | a `files[].path` matches a glob |
| draft | `isDraft` is true |
| assumptions | `<run-dir>/assumptions.md` is non-empty and `merge_with_assumptions` is false |
| base | `baseRefName` is not `base_ref()` with the remote prefix stripped |

The verdict is written to `<run-dir>/gate/<n>-merge.md` sharing the gate's numbering; there is no
`.log` file for a merge verdict. The command changes nothing in git and never merges.

## Verdict and log

With `--run`, `<n>` starts at 1 and increments across all gate calls in that run:

| call | verdict | log |
|---|---|---|
| normal | `<run-dir>/gate/<n>.md` | `<run-dir>/gate/<n>.log` |
| `--pr` | `<run-dir>/gate/<n>-pr.md` | `<run-dir>/gate/<n>-pr.log` |
| `--merge` | `<run-dir>/gate/<n>-merge.md` | none |

The verdict starts with `GATE: PASS` or `GATE: FAIL`, has `## Summary` with 4–6 bullets (one is `- Head: <sha>`, plus ` (dirty)` when `git status
--porcelain` is non-empty), lists every
failure under `## Details`, and ends with the log tail under `## Log`. A no-run verdict is the same
text on stdout.

The gate still runs `verify` after a protected-file failure, and still checks the manifest and
evidence after any failure, so one verdict names everything that needs fixing.
