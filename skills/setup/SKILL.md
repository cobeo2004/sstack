---
name: setup
description: Make a repo agent-ready for sstack, new or existing. Writes .sstack/product.md (what the app is, linking deeper docs), .sstack/project.toml, the verify commands, the code graph, and one AGENTS.md row. Use for "set up this repo", "onboard", "make this repo sstack-ready", or when work finds no .sstack/product.md on a sizeable task.
---

# setup

Run in the repo root. **If this is a linked worktree** (`git rev-parse --git-dir`
≠ `git rev-parse --git-common-dir`), say so first: `.sstack/` here is not the
repo's. Offer the primary checkout (`git worktree list --porcelain`, first entry)
and run `setup` there — sstack reads `product.md`, config and repo lessons from it
in every worktree. Continue here only if the user wants a separate setup for this
checkout.

First decide: **existing repo** (has code or docs) or **new repo** (empty or
near-empty). Re-runnable; see the last section.

## Existing repo

1. **Read what's there.** `AGENTS.md`, `CLAUDE.md`, README, `.docs/` or `docs/`,
   manifests (`package.json`, `Cargo.toml`, `pyproject.toml`, …), CI config, and
   repo-local skills in `.agents/skills/` and `.claude/skills/`. Report any repo
   skill whose name clashes with an sstack skill (`sstack setup work swarm review
   unslop babysit how why diagram code-graph reflect`); the repo's copy wins inside
   that repo, so say which.
2. **Write `.sstack/product.md`** from [templates/product.md](templates/product.md):
   what the app is, who it's for, the main flows, the surfaces and how they
   connect. **Link** to deeper docs (e.g. `.docs/spec/functional-spec.md`,
   `.docs/architecture/`) instead of copying them. Never restate what the repo
   already encodes: versions, env var names, dependency lists, scripts, folder
   trees. If a fact lives in a file an agent can read, point at the file. Keep it
   under about 60 lines.
3. **Write the repo config in the split layout** ([config spec](../../docs/spec/config.md)):
   write `.sstack/project.toml` from [templates/project.toml](templates/project.toml)
   (`brief`, `docs`, `verify`, `graph`, one `[test.<surface>]` per surface). Put repo-wide `dispatch`, `rules` or `reflect` changes
   in `.sstack/config.toml`; repo role overrides in `.sstack/roles/<role>.toml`
   and harness overrides in `.sstack/harnesses/<name>.toml`. Machine-local
   overrides go in `.sstack/local/` — add `.sstack/local/` and `.sstack/runs/` to
   `.gitignore`, or to `.git/info/exclude` if the user doesn't want `.gitignore`
   touched. Ask whether `.sstack/project.toml` and `product.md` should be
   committed; the repo decides.
4. **Find the "prove it works" commands** (lint, typecheck, test, build) from
   manifests and CI. Run each once, read the output, and propose the list for
   `verify` in `.sstack/project.toml`. Ask the user to confirm before writing it.
   Note any that need a service running first (database, emulator). Then fill
   `[test.<surface>]` for each surface the app has (code, browser, mobile; see
   [work/testing.md](../work/testing.md)): the framework and where its tests
   live, and the run / serve / build commands. Leave out a surface the app
   doesn't have. Don't add a framework unasked.
5. **Build the code graph** if `code-review-graph` is installed: see `code-graph`
   (`code-review-graph build`). If it isn't installed, say so and set
   `graph = false` in `.sstack/project.toml`; don't install it unasked.
6. **Point agents at the brief.** If `AGENTS.md` has a routing table, add one row:
   `| Any task | Read [.sstack/product.md](.sstack/product.md) first |`.
   With no table, add one plain line: `Read .sstack/product.md before any task.`
   No `AGENTS.md` → create a minimal one with that line. Leave `CLAUDE.md` alone if
   it already includes `AGENTS.md` (e.g. `@AGENTS.md`); otherwise add the same line.
7. **Register the repo** for the dashboard: append the absolute repo root to
   `~/.sstack/repos.txt` unless it's already listed. In a linked worktree register
   the primary checkout — the entry has to outlive the worktree.
8. **Ask, then smoke-test.** Ask the user whether to run the doctor smoke test.
   On yes, run `<sstack>/bin/sstack-doctor --smoke` (on exit 4, make the printed
   calls and their `record`s, then run `--smoke --check <run dir>`) and report
   every member's result.
9. **Report**: files written, verify commands and their results, graph status,
   clashes found, and what you could not determine.

## New repo

Ask the product questions one at a time (what is it, who is it for, the two or
three main flows, which surfaces: app, API, admin, workers). Then write the same
files as above plus a starter `AGENTS.md` with: one line on what the repo is, the
`.sstack/product.md` pointer, and the verify commands once they exist. Don't
invent a stack the user didn't choose.

## Re-running

Re-running refreshes `product.md` against the current repo and **shows a diff**
before writing. Never overwrite text the user wrote by hand without asking:
propose the change and wait. Config: only add missing keys; never change existing
values unasked. Step 7 is idempotent.

---
Adapted from pstack `setup-pstack` + `create-verification-skill` (michael-denyer/pstack-claude
@ 91ab921, MIT) and orbyn's skill clash check (orbyn-dev/orbyn-fullstack-skills @ 185e5a5).
