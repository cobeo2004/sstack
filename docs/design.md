# sstack — design

Date: 2026-11-08. Status: approved by the user 2026-11-08 (with the `reflect`
skill and dashboard added after review). Items marked *(builder's call)* were
settled by the author, not the user.

## Intent

One small skill stack that replaces the overlapping workflow layers the user runs
today (oh-my-claudecode, oh-my-codex, superpowers, phased-work, delegation-brief,
loose process skills). Today the workflow is scattered across those layers, a
CLAUDE.md rule has to referee them, every repo starts cold because nothing sets a
project up, and almost all delegated work lands on Claude even when another model
is better or cheaper (the main case: implementation on pi with DeepSeek).

sstack covers the workflow end to end: **set up a repo → do the work through gated
phases → utilities (diagrams, code graphs)**, with every delegated role routable to
a configured harness + model, from any ADE (T3 Code, Conductor, Orca, Cursor, a
plain terminal).

It will be edited almost daily, so it stays small and swappable: plain folders, no
build step, no generated files.

## Goals

- One entry point that routes any engineering request to the right skill/playbook.
- `setup` that makes a new or existing repo agent-ready, including a short product
  brief ("what this app is and does"), not just conventions.
- `work`: gated phases for any task (ticket ID optional) — debugging, features,
  refactors, perf, executing a plan.
- Per-role harness + model routing from TOML, global → repo → local.
- Works in any ADE: visible thread where the ADE supports it (T3), headless CLI
  everywhere else.
- Learns: captures the user's corrections and the agent's dead ends as lessons so
  they are not repeated, and turns repeated lessons into real edits.
- A light local dashboard showing lessons, code graph, roles/models (editable),
  workflows and runs — built so new pages are easy to add.
- Proven on UniBuz (`/Users/cobeo/Codes/WorkPlace/UniBuz/Unibuz_mobile`).

## Non-goals

- Domain skills (impeccable, Rust, Supabase, ElevenLabs, Vercel/React, dataviz…).
  They stay installed outside sstack and update from their own sources.
- Worktree management — the ADEs own it.
- Data charts — `dataviz` covers them.
- Per-ADE adapters beyond a transport entry in config.
- Vector/embedding memory stores, autopilot/autonomous loops, eval machinery,
  provenance/credits tooling, CI-enforced policy. (Lessons are plain files.)

## Anti-goals (failure even if it works)

- Drift: re-growing into a layer that needs refereeing. A new skill is added only
  if it is frequent and not a step of an existing skill.
- A routed child approving its own gate, committing, or opening a PR.
- Restating in prose what the repo already encodes (versions, env names, deps).
- Hard-coding Claude-only mechanics (Agent/Task tool names, plan mode,
  AskUserQuestion) in a skill body, so it breaks under Codex, pi or Cursor.
- Deleting the user's existing skills/plugins without a backup and an explicit yes.

## Constraints

- Python ≥ 3.11 stdlib only for scripts (`tomllib`, `subprocess` with timeout —
  macOS has no `timeout` binary). No npm/pip installs.
- Every SKILL.md readable by Claude Code, Codex, Cursor and pi. Harness-specific
  tool names live in one mapping note per harness, not in skill bodies.
- Gates always stay with the orchestrating session (the one the user talks to).

## Repo layout

```
sstack/
  skills/
    sstack/        SKILL.md  principles/  harness-notes/{claude,codex,cursor,pi}.md
    setup/         SKILL.md  (+ templates for product.md, config.toml)
    work/          SKILL.md  playbooks/{feature,bug-fix,refactor,perf,multi-phase}.md
    swarm/  review/  unslop/  babysit/  how/  why/  diagram/  code-graph/  reflect/
  bin/
    sstack-dispatch     # the router/launcher (Python, stdlib)
    sstack-install      # symlinks skills into each harness's skills dir
    sstack-ui           # local dashboard server (Python stdlib http.server)
  ui/                   # dashboard page(s): plain HTML/CSS/JS, no build step
  config.example.toml
  docs/design.md
  tests/                # one small stdlib test file for sstack-dispatch
```

**Install ("import locally")**: `bin/sstack-install` symlinks each `skills/<name>`
into the skills directories that exist on the machine (`~/.claude/skills`,
`~/.agents/skills`, `~/.codex/skills`, `~/.cursor/skills`; pi's dir if present),
backing up any same-named entry to `<name>.bak` first. It removes nothing else.
Retiring OMC/superpowers/old skills is a separate, manual step after UniBuz testing
passes — not part of the build.

**Triggering (user's decision): both implicit and explicit.** Implicit: skill
descriptions are written to trigger on ordinary requests, and `sstack-install`
adds one marked line (`<!-- sstack -->`, removable) to the global `CLAUDE.md` /
`AGENTS.md` that exist: "For engineering tasks, start with the `sstack` skill."
Explicit: every skill is also callable by name (`/sstack`, `/work`, `/review`,
`/setup`, …).

**Coexistence during testing (user's decision):** the UniBuz test runs with OMC
and superpowers disabled (`DISABLE_OMC=1`, superpowers plugin turned off for that
session), so it shows sstack working alone. Nothing is uninstalled.

## The skills (12)

| Skill | Purpose | Main sources |
|---|---|---|
| `sstack` | Entry router: classify the request, pick skill/playbook, copy its steps into a todo list verbatim (skipped steps stay, marked `skip: <reason>`). Holds the principles index, gate rules, verification gate, "delegate by volume" rule, harness notes. | pstack poteto-mode (cut hard), superpowers verification-before-completion, OMC verify check order |
| `setup` | New or existing repo → agent-ready. See Setup. | new; pstack setup-pstack + create-verification-skill; orbyn clash check |
| `work` | Gated phases for any task. See Work. | user's phased-work, pstack playbooks, orbyn answer key + loop guard, superpowers writing-plans granularity |
| `swarm` | Fan one question out to N children; each returns PASS/ISSUES/BLOCKED with evidence; missing evidence → respawn once, then record a gap. | pstack swarm |
| `review` | Adversarial review of a diff or PR (`review`, `review <PR#>`). Findings must reproduce (orchestrator re-runs each) or are dropped; only added/changed lines; re-check each finding against current head; reviewers ideally a different model family. Reports, does not fix. | pstack interrogate + thermo-nuclear-review rules + orbyn pr-iteration |
| `unslop` | Pre-PR cleanup of diff and PR/prose text. | pstack deslop + no-comments + unslop |
| `babysit` | Watch PR CI and review comments; fix CI; receive feedback rigorously (verify before applying, push back when wrong). | pstack babysit + fix-ci + get-pr-comments, superpowers receiving-code-review (trimmed) |
| `how` | Trace how something works, from source, cited. | pstack how |
| `why` | Why it is that way, from git history / PRs. | pstack why |
| `diagram` | Architecture, sequence, data-flow, state diagrams. Thin: grounds the picture in real code first (via `how` / `code-graph`), then drives the installed archify skill for HTML/SVG/PNG output. | user's archify (stays installed from its upstream, like domain skills) *(builder's call: archify is 8 MB, Node-based, actively maintained and already exports PNG, so copying it or adding stack-diagram's renderer would fork it for nothing)* |
| `code-graph` | Drive the installed `code-review-graph` CLI: build/update, visualize, `detect-changes` impact, wiki. | wraps existing tool |
| `reflect` | Turn the user's corrections and the agent's dead ends into lessons; when a lesson repeats, propose a structural edit (sstack skill, repo `AGENTS.md`, a check) instead of more notes. See Lessons. | pstack reflect + principle-encode-lessons-in-structure, orbyn reflect (manual capture, ≤3 suggestions) |

Not skills: `bin/sstack-dispatch` (all routing), `skills/sstack/principles/` (the 8
load-bearing principles from pstack — prove-it-works, fix-root-causes, laziness,
model-the-domain, sequence-verifiable-units, test-behavior-not-implementation,
separate-before-serializing-shared-state, guard-the-context-window — loaded on
demand from a one-line-per-principle index).

Upstream text is adapted, not vendored: each skill is rewritten short in sstack's
voice, with a one-line source credit at the bottom (pstack, orbyn, superpowers are
MIT). Sources, pinned (clone shallow into a scratch dir, never into sstack):

- pstack port: `https://github.com/michael-denyer/pstack-claude` @ `91ab921`
  (skills under `plugins/pstack/skills/`, playbooks under `poteto-mode/playbooks/`)
- orbyn: `https://github.com/orbyn-dev/orbyn-fullstack-skills` @ `185e5a5`
  (answer key: `skills/orbyn-workflow/references/answer-key.md`; stack-diagram render
  step: `skills/stack-diagram/`)
- superpowers 7.0.0: `~/.claude/plugins/cache/claude-plugins-official/superpowers/7.0.0/skills/`
- user's own: `~/.claude/skills/phased-work/SKILL.md`; archify at
  `~/.agents/skills/archify` (used, not copied — see `diagram`)

## Setup

`setup` runs in a repo root. It detects new vs existing.

Existing repo:
1. Read `AGENTS.md`, `CLAUDE.md`, README, `.docs/` or `docs/`, manifests, repo-local
   skills (`.agents/skills`, `.claude/skills`). Report name clashes with sstack skills.
2. Write `.sstack/product.md`: what the app is, who it is for, the main flows, the
   surfaces and how they connect — **linking** to deeper docs (e.g. UniBuz
   `.docs/spec/functional-spec.md`, `.docs/architecture/`) rather than copying them.
   Never restate versions, env names or dependency lists.
3. Write `.sstack/config.toml` (`[project]` section; roles only if the user wants
   repo-specific routing). Add `.sstack/config.local.toml` and `.sstack/runs/` to
   `.gitignore` (or `.git/info/exclude` if the user doesn't want to touch
   `.gitignore`).
4. Record the repo's "prove it works" commands in `[project].verify`, confirmed with
   the user.
5. Build the code graph if `code-review-graph` is installed.
6. Add one row to the `AGENTS.md` routing table (or one line if there is no table):
   "Any task → read `.sstack/product.md` first". `CLAUDE.md` is left alone if it
   already includes `AGENTS.md`.

New repo: ask the user the product questions (one at a time), then write the same
files plus a starter `AGENTS.md`.

Re-runnable: re-running refreshes `product.md` and shows a diff; it never
overwrites content the user wrote by hand without asking.

## Work

`work [TICKET-ID] <task>`. Playbook chosen by the `sstack` router: feature,
bug-fix (has a diagnose-only stop), refactor, perf, multi-phase (large work).

Phases and gates:

0. **Recon** — sync with base branch, read ticket (if any), house rules,
   `.sstack/product.md`. Clarify step: ask one question at a time, but if running
   something answers it, prototype instead of asking. Fan-out questions via `swarm`
   (role `scout`). Use `code-graph detect-changes` for impact. **Gate: report and
   stop** (SYSTEM STATE / CAUSE or PATTERN / PLAN SHAPE / TEST STRATEGY / RISKS /
   COULD NOT VERIFY — as in phased-work).
1. **Plan** — ordered, bite-sized changes with exact files and the check for each.
   Write the **answer key** before implementation: the success commands, and copies
   of the protected tests plus their hashes, saved in `.sstack/runs/<id>/`.
   **Gate: the harness's own plan approval** (plan mode in Claude Code; the
   equivalent elsewhere, or an explicit yes in chat where none exists).
2. **Implement** — role `implement`. Routed or local. No commits, no PR.
3. **Test / fix** — run the answer key; restore protected tests from their hashes
   before judging. Failures loop back to Implement with the failing checks added to
   the brief. Loop guard: same failure twice → change approach once, then stop and
   ask. `review` runs here (role `review`). **Gate: green checks + review findings
   resolved or explicitly agreed out of lane.**
4. **PR** — `unslop`, repo PR template, re-run tests on the merged result, push,
   then `babysit`. **Gate: the user's explicit yes before commit/push/PR.**

The orchestrator reads every child's report **and** the real `git diff` before any
gate. A routed child never approves its own gate. Exit code 1/2 from dispatch →
stop at the next gate and tell the user; don't silently redo the work locally.

## Routing config

Three layers, merged in order: `~/.sstack/config.toml` (global) →
`<git root>/.sstack/config.toml` (shared; repo decides whether to commit) →
`<git root>/.sstack/config.local.toml` (git-ignored, personal).

Merge rule: each `[role.X]`, `[harness.X]`, `[project]` table is replaced whole;
top-level scalars and scalars inside `[transport]`/`[rules]` override one by one;
anything unmentioned is inherited. No trust tiers (all files are the user's; add an
orbyn-style "committed file may only tighten" rule if configs are ever shared with
untrusted people).

Roles, not skills. Five roles cover every delegating skill:

| Role | Used by |
|---|---|
| `scout` | recon fan-out, how, why, code-graph |
| `investigate` | bug hypotheses, perf forensics |
| `plan` | plan drafting only (the gate stays local) |
| `implement` | work phase 2, babysit fixes |
| (`scout`, again) | automatic reflect pass at session end |
| `review` | review, plan critique, verification |

An unlisted role, or `harness = "local"`, runs in the current session.

Global example (ships as `config.example.toml`):

```toml
[harness.pi]
headless = ["pi", "-p", "--no-session", "--model", "{model}", "--thinking", "{effort}"]
t3_provider = "pi"

[harness.codex]
headless = ["codex", "exec", "--sandbox", "workspace-write", "-m", "{model}", "-c", "model_reasoning_effort={effort}", "-"]
t3_provider = "codex"

[harness.claude]
headless = ["claude", "-p", "--model", "{model}", "--permission-mode", "acceptEdits"]
t3_provider = "claudeAgent"

[harness.cursor]
headless = ["cursor-agent", "-p", "--force", "--model", "{model}"]
t3_provider = "cursor"

[transport]
mode = "auto"            # auto | thread | headless | local
timeout_min = 30

[transport.t3]
detect = "T3CODE_THREAD_ID"          # env var present inside T3 Code
cli = "$T3CODE_CLI_PATH"             # falls back to ~/.t3/bin/t3
cmd = ["{cli}", "thread", "start", "--provider", "{provider}", "--model", "{model}",
       "--title", "{title}", "--wait", ".", "-"]

[role.scout]
harness = "claude"
model = "haiku"

[role.implement]
harness = "pi"
model = "opencode-go/deepseek-v4.1-flash"
effort = "high"

[role.review]
panel = [
  { harness = "codex",  model = "gpt-6.1-sol", effort = "high" },
  { harness = "claude", model = "opus" },
]

[rules]
review_not_implementer = true   # drop any panel member equal to role.implement
max_parallel = 4
loop_guard = 2
```

Repo example (`.sstack/config.toml`):

```toml
[project]
brief  = ".sstack/product.md"
docs   = [".docs/spec/functional-spec.md", ".docs/architecture/"]
verify = ["pnpm lint", "pnpm test"]
graph  = true
```

Read-only roles *(builder's call, marked)*: `scout`, `investigate` and `review` run
in the user's working tree in parallel, so "don't edit" is enforced, not just
asked. Each harness may declare `headless_readonly` (e.g. codex
`--sandbox read-only`, claude `--permission-mode plan`, pi `--tools read,grep,find,ls`),
and dispatch uses it for those roles. A read-only role on a harness without
`headless_readonly` is refused (exit 1 with a message), not silently run with
write access. After any child, dispatch checks `git status` and records any
change a read-only child made in the report.

Model ids are the same string in headless pi and in T3's pi provider
(`provider/model`, e.g. `opencode-go/deepseek-v4.1-flash`), verified against
`pi --list-models` and T3's provider catalog on 2026-11-08. Template placeholders
whose value is unset (e.g. no `effort`) are dropped together with their flag.

## sstack-dispatch contract

```
sstack-dispatch <role> --brief <file> --report <file> [--title <t>] [--dry-run]
```

- Resolves config layers from the git root of the current directory.
- Transport (`mode = auto`): if `[transport.t3].detect` env var is set **and** the
  role's harness has `t3_provider` → T3 thread (visible); else the harness's
  `headless` command. `thread` forces T3 (error if unavailable), `headless` forces
  CLI, `local` makes every role local.
- Runs in the git root, brief on stdin, stdout captured to `--report`; enforces
  `timeout_min` (kills the child process group).
- `review` with a `panel`: runs members in parallel (≤ `max_parallel`), writes one
  report per member (`<report>.<harness>-<model>.md`) and an index.
- Exit codes: `0` ok and report non-empty; `1` child failed or empty report;
  `2` timeout; `3` role is local/unconfigured (prints `local`). T3's own
  `--wait` exit 2 ("agent is waiting for an answer") maps to dispatch exit 1.
- Panel results *(builder's call)*: exit 0 if at least one member returned a
  report, with failed/timed-out members listed as gaps in the index; exit 1 if
  none did. `work` treats a gap as a reason to tell the user at the gate, not to
  pass silently.
- Effort in T3 *(builder's call)*: `t3 thread start` has no effort flag, so a
  role's `effort` is dropped in a T3 thread and the dry run says so. When the
  orchestrator uses T3's native `delegate_task` instead, it passes effort as a
  provider option.
- `--dry-run` prints the resolved transport and command per member, runs nothing.
- `plan` may be routed for drafting, but dispatch never runs a gate.

Brief template (written by the orchestrator to `.sstack/runs/<id>/<role>-<n>.brief.md`):
lane, the approved plan or the recon questions, "read AGENTS.md/CLAUDE.md and
.sstack/product.md", "no commits, no PR, no questions to the user", and the report
contract below.

Report contract (child's final message): files changed; what it did; what it could
not do; status `PASS | ISSUES | BLOCKED` with evidence (commands run + output).

In T3 Code, the orchestrator may use T3's native `delegate_task` tool instead of the
CLI when the configured provider is available there — same brief, same report
contract.

## Lessons (`reflect`)

What counts: the user's corrections ("don't do X", "I told you…") and the agent's
dead ends in the code ("this approach already failed here, because…"). One-offs
are not lessons.

Storage — plain files every harness can read:
- `<git root>/.sstack/lessons.md` for repo lessons (committed or not — repo's choice,
  like config).
- `~/.sstack/lessons.md` for lessons about the user / general practice.

Format *(builder's call)*: one lesson per list item, machine-parseable so the
dashboard can edit it:

```
- [pending] seen=1 id=L7 | Backend tests need `supabase start` first | evidence: run 2026-11-08 UNI-142, ECONNREFUSED
- [accepted] seen=3 id=L3 | Never bare `git stash` in a worktree | encoded: skills/work/SKILL.md
```

Statuses: `pending` (proposed, not trusted yet) → `accepted` (read by agents) →
`encoded: <target>` (turned into structure; kept as history). `forget` deletes the
line. Agents read only `accepted` lessons: the `sstack` router reads both lesson
files at the start of a task (accepted lines only, so it stays short).

Capture:
- **Manual, any harness:** "reflect" / `/reflect` reviews the current session and
  proposes at most 3 lessons as `pending`. The user accepts in chat or in the
  dashboard.
- **Automatic, where the harness has an end-of-session hook** (Claude Code
  `SessionEnd`/`Stop`; Codex and pi where supported): the hook runs
  `sstack-dispatch scout` with a reflect brief over the session transcript and
  appends proposals as `pending`. Opt-in via `[reflect] auto = true`; never writes
  `accepted`.
- **Repeat → structure:** when a lesson's `seen` reaches 2 (configurable
  `[reflect] encode_at`), reflect proposes a concrete edit — the sstack skill,
  the repo's `AGENTS.md`/skill, or a check/script — and shows the diff; it is
  applied only with the user's yes.

## Dashboard (`sstack-ui`)

`bin/sstack-ui [--port N]` serves a local page on `127.0.0.1` (stdlib
`http.server`, random free port by default, prints the URL). Layout: sidebar, one
page per area (user chose this over a single overview; see the clickable preview
from the brainstorm).

- **Top bar:** repo switcher (every repo listed in `~/.sstack/repos.txt`, which
  `setup` appends to) + a "global" view; current transport.
- **Overview:** product one-liner from `.sstack/product.md`, counts (lessons to
  review, runs this week), implement route, graph freshness, last run.
- **Lessons:** both lesson files; Accept / Forget for `pending`; shows `encoded`
  targets.
- **Code graph:** embeds/opens `code-review-graph visualize` output; Rebuild
  button runs `code-review-graph update`.
- **Roles & models:** merged view of the three config layers with the source layer
  per value; edit harness/model/effort; choose which layer to save to
  (local / repo / global). Writes TOML.
- **Workflows:** the `work` phases with the role and gate for each, and the
  playbooks (bundled + repo overrides in `.sstack/playbooks/`).
- **Runs:** `.sstack/runs/index.jsonl` (appended by `sstack-dispatch` on every
  run: time, task, role, harness, model, transport, exit code, duration, report
  path); click through to the brief and report.

Data rules: the dashboard reads and writes only the same files agents use; it has
no database of its own. It binds to localhost only and requires a random token
in the URL *(builder's call)*. Extending = one more HTML section + one JSON
endpoint that reads one more file.

TOML writing *(builder's call)*: stdlib has no TOML writer, so `sstack-ui` writes
only the `[role.*]` tables it edits, with a tiny emitter for that fixed shape,
and leaves the rest of the file's text untouched.

## Verification of the build

1. `sstack-dispatch implement --dry-run` prints pi + `opencode-go/deepseek-v4.1-flash`
   (headless outside T3, T3 thread inside T3).
2. Repo `.sstack/config.toml` switching implement to codex → dry run shows codex;
   `config.local.toml` switching it back → shows pi.
3. Real run in a scratch git repo: brief "create hello.txt containing hi", role
   implement on pi → file exists, report non-empty, exit 0.
4. Fake harness `["sleep","10"]` with `timeout_min = 0.05` → exit 2.
5. Unconfigured role → exit 3 + `local`; `harness = "local"` → exit 3.
6. Review panel dry run drops a member equal to implement.
7. `sstack-install` creates the symlinks and backs up clashes; skills load in Claude
   Code and Codex.
8. `sstack-ui` starts, every page loads against a scratch repo with sample
   lessons/runs; Accept/Forget rewrites `lessons.md` correctly; saving a role to
   `local` changes the next `sstack-dispatch --dry-run`.
9. `reflect` on a session with a planted correction proposes it as `pending`;
   accepting it makes it visible to the router; a second sighting proposes an edit.
10. UniBuz: run `setup`, check `.sstack/product.md` links to the spec rather than
   copying it, and the `AGENTS.md` row; then run one small `work` task end to end
   with implement on pi.

## Left to the builder

- Exact wording and length of each SKILL.md (target: each under ~150 lines; the
  `sstack` router under ~200).
- Harness-note contents (tool-name mappings for Claude, Codex, Cursor, pi).
- Internal structure of `sstack-dispatch` (single file; one stdlib test file).
- Brief/report file naming details under `.sstack/runs/`.
- What counts as a "new" repo for `setup` (e.g. no commits beyond the initial one,
  or no app code).
- What `diagram` does when archify is not installed (say so and offer a plain
  Mermaid block).
