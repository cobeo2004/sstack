---
name: setup
description: Make a repo agent-ready for sstack, new or existing. Audits the repo and the machine read-only, shows one table of recommended changes, and writes only the rows the user picks - .sstack/product.md (what the app is, linking deeper docs), .sstack/project.toml, the verify commands, the code graph, and one AGENTS.md row. Use for "set up this repo", "onboard", "make this repo sstack-ready", or when work finds no .sstack/product.md on a sizeable task.
---

# setup

Run in the repo root. **If this is a linked worktree** (`git rev-parse --git-dir` ≠
`git rev-parse --git-common-dir`), say so first: `.sstack/` here is not the repo's. Offer the primary
checkout (`git worktree list --porcelain`, first entry) and run `setup` there — sstack reads
`product.md`, config and repo lessons from it in every worktree. Continue here only if the user wants
a separate setup for this checkout. Unattended (§3): never ask or move; set up this checkout.

Audit, recommend, ask, and only then write. **Nothing is written before the user chooses.** Works on
an existing repo and a new one; re-runnable, see the last section.

## 1. Audit

Read-only: change nothing, write nothing — `~/.sstack/repos.txt` included.

Repo: what already exists of each thing setup writes — `.sstack/product.md`, `.sstack/project.toml`
(and `config.toml`, `roles/`, `harnesses/`, `local/`), the `.gitignore` or `.git/info/exclude`
entries, the `AGENTS.md` row, the code graph — then `AGENTS.md`, `CLAUDE.md`, README, `.docs/` or
`docs/`, manifests, CI config, and repo-local skills in `.agents/skills/` and `.claude/skills/`.
Report any repo skill whose name clashes with an sstack skill (`sstack setup work swarm review unslop
babysit how why diagram code-graph reflect practices`): the repo's copy wins inside that repo, so say which.
From manifests and CI, list the candidate "prove it works" commands (lint, typecheck, test, build),
read each script first, and run only the ones that cannot change tracked files (no `--fix`,
`--write`, `-u`/snapshot updates, codegen); keep each one's output and exit code, and note any needing
a service first. A command that writes, or that you can't tell, is not run: it becomes a row
("run `<cmd>` to confirm it") for Choose.

Machine, read-only: `<sstack>/bin/sstack-doctor` and `<sstack>/bin/sstack-config show`; each agent's
global instruction file (`~/.claude/CLAUDE.md`, `~/.codex/AGENTS.md`, `~/.cursor/AGENTS.md`,
`~/.pi/agent/AGENTS.md`) — does it carry the sstack pointer the installer adds, and is a contradicting
rule ("… first", "without asking") above it? (`sstack-doctor` reports this as `entry pointers`);
skills or plugins installed beside an sstack skill that do the same job (`~/.claude/skills`,
`~/.agents/skills`, `~/.codex/skills`, `~/.cursor/skills`, `~/.pi/agent/skills`).

## 2. Recommend

One table, still nothing written: `#`, action, where, current → proposed, why, and default
(`recommended` or `optional`) — one row per change, from the audit only, no invented stack and no
install unasked. Typical rows: `product.md`, the `project.toml` keys (`brief`, `docs`, `verify`,
`protected`, `graph`, one `[test.<surface>]` per surface), the ignore entries, the `AGENTS.md` row,
the repo registration, the code graph, and the machine rows the audit found (instruction files,
duplicate skills).

## 3. Choose

`<sstack>/bin/sstack-workflow unattended` prints `unattended: on` → nobody is in the thread: skip the
ask, apply every row marked `recommended` (`.sstack/product.md`, `.sstack/project.toml` with the
audit's verify commands, the ignore entries), never an `optional` or machine row, then report which
rows you wrote and which you skipped.

Ask the user, with the harness's ask-the-user verb (multi-select where it has one), which numbered
rows to apply. **Nothing is written before the user chooses.** Rows not picked are not written, and
the report says which were skipped.

## 4. Apply

Only the chosen rows.

1. **`.sstack/product.md`** from [templates/product.md](templates/product.md): what the app is, who
   it's for, the main flows, the surfaces and how they connect. **Link** to deeper docs (e.g.
   `.docs/spec/functional-spec.md`, `.docs/architecture/`) instead of copying them. Link the repo's own
   glossary (`CONTEXT.md`, `GLOSSARY.md`, `docs/glossary*`) and decision records (`docs/adr/`,
   `docs/decisions/`) when they exist; `grill` and `work` write settled terms back to that glossary and
   read those ADRs. Never create either; no glossary → say so in the report. Never restate
   what the repo already encodes: versions, env var names, dependency lists, scripts, folder trees.
   If a fact lives in a file an agent can read, point at the file. Under about 60 lines.
2. **The repo config in the split layout** ([config spec](../../docs/spec/config.md)):
   `.sstack/project.toml` from [templates/project.toml](templates/project.toml) (`brief`, `docs`,
   `verify`, `protected`, `graph`, one `[test.<surface>]` per surface the app has — code, browser,
   mobile; see
   [work/testing.md](../work/testing.md) — with its framework, where its tests live, and the run /
   serve / build commands; leave out absent surfaces). `dispatch`, `rules` or `reflect` changes go in
   `.sstack/config.toml`, role overrides in `.sstack/roles/<role>.toml`, harness overrides in
   `.sstack/harnesses/<name>.toml`, machine-local overrides in `.sstack/local/`. Add `.sstack/local/`
   and `.sstack/runs/` to `.gitignore`, or to `.git/info/exclude` if the user doesn't want
   `.gitignore` touched. Ask whether `project.toml` and `product.md` should be committed.
3. **The verify commands and protected globs** from the audit in `verify`/`protected`, with their
   results. Then run `practices`
   with the audit's stack: it proposes `[practices]` in `project.toml` (globs → skills or docs that
   dispatched children read) and writes only on the user's yes. Drop any that need a
   service you don't have; add none the user didn't see at Choose.
   Propose `check`: the fastest one-file check (`{path}` = the edited file). On yes, offer the
   post-edit hook snippet from your harness note, and say to run the same `check` in CI: edits made
   through the shell fire no hook.
4. **The code graph** if `code-review-graph` is installed: see `code-graph` (`code-review-graph
   build`). If not, say so and set `graph = false`; don't install it unasked.
5. **Point agents at the brief.** If `AGENTS.md` has a routing table, add one row:
   `| Any task | Read [.sstack/product.md](.sstack/product.md) first |`. With no table, add one plain
   line: `Read .sstack/product.md before any task.` No `AGENTS.md` → create a minimal one with that
   line. Leave `CLAUDE.md` alone if it already includes `AGENTS.md` (e.g. `@AGENTS.md`); otherwise add
   the same line.
6. **Register the repo** for the dashboard: append the absolute repo root to `~/.sstack/repos.txt`
   unless it's already listed. In a linked worktree register the primary checkout — the entry has to
   outlive the worktree.
7. **Machine rows — always opt-in, never on by default.** Back the file up first (`cp <file>
   <file>.pre-sstack-<date>`), then make the smallest edit that does the job: put the sstack rule
   above the contradicting one and say it wins, or reword that rule; the row shows the exact
   before → after. Leave tool-managed blocks (`<!-- OMC:START -->` …) untouched. A duplicate skill is
   moved to a backup dir, never deleted. Cursor user rules live in Cursor settings, so give the user
   the text to paste.
8. **Smoke test.** Ask before running it (unattended: skip it). On yes, run `<sstack>/bin/sstack-doctor --smoke` (on exit 4,
   make the printed calls and their `record`s, then run `--smoke --check <run dir>`) and report every
   member's result.

## 5. Report

Files written and skipped, the verify commands and their results, graph status, skill clashes, machine
rows applied with their backups, and what you could not determine.

## New repo

Ask the product questions one at a time (what is it, who is it for, the two or three main flows, which
surfaces: app, API, admin, workers), then the same Recommend → Choose → Apply. Write the same files
plus a starter `AGENTS.md`: one line on what the repo is, the `.sstack/product.md` pointer, and the
verify commands once they exist. Don't invent a stack the user didn't choose.

## Re-running

Audit again, show it as a diff against last time, and recommend only what changed. Re-running refreshes
`product.md` against the repo and **shows a diff** before writing. Never overwrite text the user wrote
by hand without asking: propose the change and wait. Config: only add missing keys; never change
existing values unasked. Registering the repo is idempotent.

**Drift check, report only.** Nothing is rewritten without a yes. Compare what the repo says about
itself with the code, over `.sstack/product.md`, `AGENTS.md` (and `CLAUDE.md` when it stands alone),
and every `docs` entry in `project.toml`. Label each item:

| label | means |
|---|---|
| `Missing` | the file, path or command it names is gone |
| `Changed` | both exist, the claim no longer holds |
| `Extra` | code no doc names, or a `docs` entry nothing reads |
| `Moved` | it exists at a new path |
| `Unverifiable` | no check from here, and why |

Anchor both sides: `<file>:<line>` for the claim, the code path (with `file:line` where it is one) for
the evidence. Worst first: `Missing` and `Changed`, then `Moved` and `Extra`, then `Unverifiable`.

**Stack with no practices.** When the manifests name a language, framework or database and
`project.toml` has no `[practices]` entry for it, say so and offer to run `practices`.

---
Adapted from pstack `setup-pstack` + `create-verification-skill` (michael-denyer/pstack-claude
@ 91ab921, MIT) and orbyn's skill clash check (orbyn-dev/orbyn-fullstack-skills @ 185e5a5).
