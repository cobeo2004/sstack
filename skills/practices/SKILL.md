---
name: practices
description: Find best-practice skills and docs for the repo's stack and link them in .sstack/project.toml `[practices]` so dispatched children read them. Use for "best practices for this stack", "link skills to this repo", "what conventions apply here", or from setup.
---

# practices

Run in the repo root. Writes nothing before step 5's diff is approved.
Runnable alone, and called by `setup` after the verify commands.

## 1. Detect the stack

Read manifests, never guess: `package.json`, `pyproject.toml`, `setup.cfg`, `Cargo.toml`,
`go.mod`, `Gemfile`, `pom.xml` or `build.gradle*`, `composer.json`, `*.csproj`,
`Dockerfile`, `compose.y*ml`, `Makefile`, and CI config (`.github/workflows/`,
`.gitlab-ci.yml`). Note the repo's own shape too: `skills/*/SKILL.md`, `docs/`, `ui/`.
Write the stack as a short list, e.g. `python-stdlib-cli`, `markdown-skills`,
`react+typescript`, `postgres`. No manifest and no code → say so and stop: there is
no stack to link practices for.

## 2. Find practices, in this order

1. **Repo docs and conventions** — `AGENTS.md`, `CLAUDE.md`, `CODING_STANDARDS.md`,
   `CONTRIBUTING.md`, `STYLE.md`, `docs/spec/`, `docs/adr/`, `docs/decisions/`,
   `.docs/`, `.cursor/rules`. They are the repo's own truth and outrank every
   third-party skill.
2. **Installed skills** — in dispatch's order (`lib/sstack_skills.py` `path()`): each
   member harness's `skill_dirs` (defaults `~/.claude/skills`, `~/.codex/skills`,
   `~/.cursor/skills`, `~/.pi/agent/skills`, plus `~/.agents/skills`), then repo
   `.agents/skills`, `.claude/skills`, `.pi/skills`, then `<sstack>/skills`. The first
   copy of a name wins, so vet that copy and name any it shadows. Keep the ones whose
   `description` names the stack or its task (a testing skill for a test-heavy module).
3. **The `find-skills` registry** — search for the stack plus the task ("python cli
   argument parsing"), read the descriptions, prefer narrow ones with a real
   `SKILL.md`. This is where an install candidate comes from.
4. **Context7 (`ctx7`)** — for libraries the repo depends on: resolve the library
   id, read the topic that matches the code, and link the doc URL. Not a shell
   command, not a copy of the docs.

Stop early: a glob level 1 already covers needs no third-party entry.

## 3. Vet before you link

Open every third-party `SKILL.md` and every doc you intend to name. Summarise each
in one line: what it enforces, and where it clashes with this repo's own docs. A
skill that contradicts `AGENTS.md` or a spec is dropped, with the rule it breaks
named. Never link a skill from its name or its description alone.

## 4. Propose the table

`.sstack/project.toml` `[practices]` maps globs of `--files` paths to entries: a
skill name for a skill, a repo-relative path for a doc, a URL only when nothing in
the repo covers it (see [config spec](../../docs/spec/config.md#layers)).

```toml
[practices]
"web/**"   = ["react-best-practices", "docs/web/conventions.md"]
"lib/**"   = ["docs/spec/config.md"]
```

Keep globs as narrow as the evidence: one per surface or area, not `"*"` — a
`[practices]` entry reaches every child whose `--files` match it. Show the table with
each entry's source level and one-line summary, and say which globs found nothing: a
gap is a finding, not a failure.

## 5. Install only on yes

Ask per entry. A skill already present in a harness-wide dir (`~/.claude/skills`,
`~/.agents/skills`, …) is linked as is: use the global install, write nothing. A new
install goes into the repo's `.agents/skills/` **only if the user picks that**;
otherwise link what is installed and stop. No install without a yes, ever.

Then show the `git diff` of `.sstack/project.toml` and wait. Merge into an existing
`[practices]`: keep its other keys, and never rewrite a line the user wrote by hand.

## 6. Report

The stack, every entry with its source level and summary, what was installed and
where, the final table, and what you could not determine.
