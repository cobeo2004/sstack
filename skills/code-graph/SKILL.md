---
name: code-graph
description: Drive the installed code-review-graph CLI - build or update the repo's code graph, check status, export an interactive view, and get the impact (blast radius) of a diff with detect-changes. Use in setup (build), recon (what does this change touch), before a PR (impact summary), and for "graph the code", "what calls X", "what does this touch".
---

# code-graph

Wraps `code-review-graph`. If `command -v code-review-graph` finds nothing, say
so and continue without the graph; **don't install it unasked**. The graph lives
in `.code-review-graph/` at the repo root (git-ignore it).

## Commands

| When | Command |
|---|---|
| `setup`, or no graph yet | `code-review-graph build` |
| After pulling or editing, before using the graph | `code-review-graph update --base <ref>` (default base `HEAD~1`) |
| Is it built and fresh? | `code-review-graph status` (creates an empty DB if none exists; check for `.code-review-graph/` first) |
| Impact of a change (recon, review, PR) | `code-review-graph detect-changes --base <base-branch-or-sha>` (`--brief` for a summary) |
| Interactive picture for the user | `code-review-graph visualize` (HTML; `--serve` serves it on localhost:8765; `--format svg\|graphml\|…`; `--mode community\|file\|full`) |
| Generated wiki of modules | `code-review-graph wiki` (`--force` to regenerate) |

All accept `--repo <root>`; the default is auto-detected. Large repos:
`build --skip-flows` is faster (signatures and search only).

## How sstack uses it

- **setup** step 5: `build`, then `status` to confirm counts.
- **work** Phase 0: `update`, then `detect-changes --base <base>` to list what the
  intended change reaches; put the result under SYSTEM STATE / RISKS.
- **review** / Phase 4: `detect-changes` on the final diff for the impact summary
  in the PR; any reached area without a test is a review lens.
- **diagram** and **how**: callers, callees and module dependencies.
- The dashboard's Code graph page shows `status` and runs `update` (or `build`).

The graph is a map, not proof: confirm a load-bearing edge by reading the cited
code before acting on it.
