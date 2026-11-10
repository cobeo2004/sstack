# Hooks contract

One entry point for every harness hook: `bin/sstack-hook`. Each harness's hook config runs it with
the harness's JSON payload on stdin; it normalizes the payload and does the work. It never fails
the agent's session on bad input: unparsable or non-object stdin → exit 0.

```
sstack-hook post-edit   --harness claude|codex|cursor|pi [--print-normalized]
sstack-hook session-end --harness claude|codex|cursor|pi [--print-normalized]
```

`--print-normalized` prints the normalized JSON (below) on stdout and exits 0, doing nothing else.

## Normalized form

```
{"harness": "<h>", "event": "post-edit" | "session-end", "cwd": "<abs dir>",
 "transcript": "<path>" | null, "files": ["<abs path>", ...]}
```

`files` is empty for `session-end`. Relative paths are joined to `cwd`. `cwd` falls back to the
hook process's cwd when the payload has none.

| harness | cwd | transcript | files (post-edit) |
|---|---|---|---|
| claude | `cwd` | `transcript_path` | `tool_input.file_path` |
| codex | `cwd` | `transcript_path` | `tool_input.file_path`, else every `*** Add File:`, `*** Update File:` and `*** Move to:` path in `tool_input.command` (the `apply_patch` text; codex sends no path field) |
| cursor | `workspace_roots[0]` | `transcript_path` (may be null) | `file_path` |
| pi | `cwd` | `session_file` | `input.path` |

Payload fixtures: `tests/fixtures/payloads/hook-<harness>-<event>.json`. Each has a `_source` field:

| fixture | source |
|---|---|
| claude, codex, cursor | recorded from a real hook run on 2026-11-09 (claude, codex-cli 0.167.0, cursor-agent 2026.09.28), paths scrubbed |
| pi | defined by `defaults/hooks/pi-sstack.ts`; pi has no shell hooks, so the extension builds this payload from pi's `tool_result` / `session_shutdown` events (field names from pi's `docs/extensions.md`) |
| `cursor-session-end-no-transcript` | hand-made: cursor's `transcript_path` is null when transcripts are off |

## post-edit

Reads `check` from the repo's `.sstack/project.toml` (top level, a shell command with a `{path}`
placeholder; see [config.md](config.md)). No repo, no `check` → exit 0. `check` comes from the
repo, so it runs only in a repo the user registered: its root, or its primary checkout's, is a line
of `~/.sstack/repos.txt` (`setup` adds it once the user picks that row). An unregistered repo prints
`sstack-hook: <root> is not in ~/.sstack/repos.txt; check skipped` to stderr and exits 0. For each normalized file
that exists inside the repo, runs `check` with `sh -c` in the repo root. `{path}` (bare or already
quoted, `"{path}"` / `'{path}'`) becomes `"$1"` and the repo-relative path is passed as `$1`, so a
file name is never parsed as shell. A deleted file or one outside the repo is skipped. Each run gets
120 s; on timeout its whole process group is killed and it counts as a failure (`timed out after 120s`).

Any failure: stderr gets `sstack-hook: check failed: <path>` plus the command's output, one block
per failing file. Exit code:

| harness | on failure | why |
|---|---|---|
| claude, codex | exit 2 | both feed exit 2 + stderr back to the agent |
| pi | exit 2 | the extension turns a non-zero exit into `isError: true` plus the stderr text on the tool result |
| cursor | exit 0 | `afterFileEdit` output is not fed back to the agent; stderr lands in Cursor's hook log |

Shell-made edits fire no edit hook on any harness, so the same `check` belongs in CI too.

## session-end

No transcript → stderr `reflect: skipped (no transcript)`, exit 0. Otherwise runs
`bin/sstack-reflect-hook` with `{"cwd", "session_id", "transcript_path"}` on stdin
(`session_id` = the payload's `session_id`, else the transcript path) and exits 0;
`sstack-reflect-hook` detaches its background pass at once and does nothing unless
`[reflect] auto = true`. Each pass writes `.sstack/runs/reflect/<YYYYMMDD-HHMMSS>/`; its dispatch
nests at `dispatch/<HHMM>-<role>/`, and the per-session offsets live in
`.sstack/runs/reflect/state.json`. When that file is missing, the old
`.sstack/runs/reflect-state.json` is read once. `sstack-reflect-hook` also stays a Claude
`SessionEnd` entry point of its own: it reads Claude's payload as is.

## Hook snippets

Each harness note (`skills/sstack/harness-notes/<h>.md`) has one row per hook: `| post-edit hook |`
and `| end-of-session hook |`, a snippet or `none: <reason>` (`tests/test_skills.py` `HOOK_ROWS`).
`sstack-install` prints the snippets for each harness whose skill dir exists and writes no harness
settings.
