# Overnight

## What this is

The `overnight` skill takes one bedtime list of runs, drives each through
[the workflow](workflow.md) in order, and leaves you a report: merged PRs, open PRs with their
reasons, drafts, and parked runs. While it runs, the chain's gates are answered for that session
only, so nothing waits for your yes through the night.

A PR is merged only when `sstack-gate --merge` says so. That verdict reads the `[overnight]` policy
from the base branch — a branch cannot loosen the policy it is merged under — and checks the gate's
`--pr` evidence taken on the PR head commit, the review score, CI, conflicts with base, the diff size, `never_merge` globs,
draft state, and the run's `assumptions.md`. The default is `merge = "never"`: overnight opens the
PRs and leaves them to you. Contracts: [docs/spec/gate.md](../spec/gate.md) and
[docs/spec/config.md](../spec/config.md).

## Before you start

Every block on this page assumes sstack's commands are on `PATH`, as after
[Install](getting-started.md#install), and works with `SSTACK_HOME` and `TMPDIR` unset:

```sh
export PATH="$HOME/sstack/bin:$PATH"   # where getting-started.md cloned sstack
sstack-config sync >/dev/null          # your ~/.sstack profile, as sstack-install creates it
```

The machine also needs `gh`, logged in, and the repo must be registered in
`~/.sstack/repos.txt`; `setup` does that. An unregistered repo makes every `--merge` exit 2.

Start it at bedtime with the runs you want, or with a confirmed `decisions.md`: `overnight <run>...`.
With nothing given it continues the current in-progress run.

## Decide on a PR

`sstack-gate --merge <pr> --run <run>` prints its verdict as the first line and writes it to
`<run>/gate/<n>-merge.md`. The exit code is the verdict: 0 `MERGE`, 1 `HOLD: <reasons>`, 2 a setup
error (no `gh`, or the repo is not trusted). A `HOLD` names every failing check, so the reason a PR
stayed open is in the file.

This block fakes `gh` and a finished run, holds the gate, then sets `merge = "policy"` in the home
layer to show the same PR pass:

```sh
home="${SSTACK_HOME:-$HOME/.sstack}"
mkdir -p "$home"
git rev-parse --show-toplevel >> "$home/repos.txt"
run=$(mktemp -d)
mkdir -p "$run/gate"
printf 'GATE: PASS\n\n- Head: %s\n' "$(git rev-parse HEAD)" > "$run/gate/1-pr.md"
printf '[{"reviewer": "x", "score": 9, "findings": []}]\n' > "$run/findings.json"
sstack-workflow done review --run "$run" --findings "$run/findings.json"
fake=$(mktemp -d)
cat > "$fake/gh" <<'EOF'
#!/bin/sh
printf '{"headRefOid":"%s","isDraft":false,"mergeable":"MERGEABLE","baseRefName":"%s","statusCheckRollup":[],"additions":10,"deletions":2,"files":[{"path":"lib/x.py"}]}\n' "$(git rev-parse HEAD)" "$(git rev-parse --abbrev-ref HEAD)"
EOF
chmod +x "$fake/gh"
PATH="$fake:$PATH" sstack-gate --merge 7 --run "$run"      # exit 1
head -1 "$run/gate/2-merge.md"
printf '[overnight]\nmerge = "policy"\n' > "$home/config.toml"
PATH="$fake:$PATH" sstack-gate --merge 7 --run "$run"
head -1 "$run/gate/3-merge.md"
```

```text
# expect
HOLD: merge policy is 'never', not 'policy'
MERGE
```

The first call also reports the layer each part of the policy came from. A repo `.sstack/config.toml`
counts only after it is on the default branch; until then the verdict reads the working-tree copy and
says so.

`overnight` then runs `gh pr merge` with `[overnight].method` and deletes the branch, but only after a
`MERGE`. Everything else, including a draft, a red CI run or a `HOLD`, stays open and is reported.

## What the keys do

| key | default | effect |
|---|---|---|
| `merge` | `"never"` | `never` opens PRs and never merges; `policy` merges what the check allows |
| `method` | `"merge"` | `gh pr merge` method: `merge`, `squash` or `rebase` |
| `merge_min_score` | `8` | the review score (1–10) a policy merge needs |
| `max_diff_lines` | `400` | additions + deletions a policy merge allows |
| `never_merge` | `[]` | globs; a PR touching one is never merged |
| `merge_with_assumptions` | `false` | `true` merges a run that decided assumptions |
| `on_question` | `"decide"` | `decide` answers and logs to `assumptions.md`; `park` stops that run |
| `on_stuck` | `"draft"` | `draft` opens a draft PR after one more attempt; `park` leaves it stopped |
| `stop_at` | `""` | local `HH:MM`, taken as its next occurrence at start; no run starts after it |

`stop_at`, `on_question` and `on_stuck` are read by the skill, not by the gate; the rest are read by
`sstack-gate --merge`. `sstack-doctor` fails on any value outside the ranges in
[docs/spec/config.md](../spec/config.md).

## In `work`

`overnight` changes no step: it runs `work` on each listed run, answers that run's gates, and calls
`--merge` after each PR and again between runs. Because the `pr` step gates before the commit, it
runs `sstack-gate --run <run> --pr` once more on the pushed commit first. `sstack-workflow done review`
records a fingerprint of the change it reviewed (`patch` in `workflow.json`: a sha256 of the diff
from the merge base, whitespace included); `--merge` computes it for the PR's head commit and holds
when they differ, so a fix after review means a fresh review. A rebase onto unrelated files keeps the
fingerprint; one that touches the same files asks for a fresh review. A `ci: failed` hold gets the
one CI fix attempt even when other reasons also hold. The `pr` gate stays locked, and the hard-coded never
list (force-push, history rewrite, merging into a branch that is not the default, protected files,
config migration, releases, deploys, edits to any sstack config layer) parks the run instead. A
parked run resumes in the morning with plain `work` from its run dir; there is no overnight-specific
resume.

## How to change this

- Skill: `skills/overnight/SKILL.md`. Policy keys: `[overnight]` in `defaults/config.toml`.
- Code: `lib/sstack_gate.py` (`_policy`, `_merge_reasons`, `_evaluate_merge`); `lib/sstack_doctor.py`
  (`_overnight`) validates the values.
- Specs first: [docs/spec/gate.md](../spec/gate.md) for the verdict, [docs/spec/config.md](../spec/config.md)
  for the keys.
- Tests: `python3 -m unittest discover -s tests -p test_overnight.py`, then the full suite and this
  page's check, `python3 -m unittest discover -s tests -p test_docs.py`.
