# Claude Code

| Generic verb | Claude Code |
|---|---|
| ask the user | `AskUserQuestion` (one question, 2–4 options); plain chat if unavailable |
| plan gate | `EnterPlanMode` to draft, `ExitPlanMode` for the user's approval |
| todo list | `TaskCreate`/`TaskUpdate`, or `TodoWrite` where configured |
| spawn a native subagent | `Agent(...)` — only for local roles; routed roles use `dispatch` ([sstack](../SKILL.md#delegation)), whose payload is itself `Agent` calls when no ADE is active |
| drive a browser | the active ADE's note; else an MCP browser tool or browser skill the session has (e.g. Playwright MCP); else headless Playwright from the shell |
| drive a device | the active ADE's note; else the repo's mobile runner (e.g. `maestro test`) from the shell |
| post-edit hook | `PostToolUse` matcher `Edit\|Write` in `~/.claude/settings.json` → `<sstack>/bin/sstack-hook post-edit --harness claude`; a failing `check` (exit 2) is fed back (the installer prints the snippet) |
| end-of-session hook | `SessionEnd` hook in `~/.claude/settings.json` → `<sstack>/bin/sstack-reflect-hook` (the installer prints the snippet) |

- Headless child: `claude -p --model <m>`; read-only roles use
  `--permission-mode plan` (set in `~/.sstack/harnesses/claude.toml`, synced from the template).
- Claude Code is a harness, not an ADE. With no ADE detected (a detected ADE always wins),
  `CLAUDECODE` makes it the session harness: a dispatch exits `4` with
  `"ade": null, "session": "claude"` and calls from `harnesses/claude.toml` `[session]`.
  Make each call as given, in one message when there are several.
  - A Claude member is an `Agent` call (`subagent_type: general-purpose`). Read-only roles get
    no isolation; `implement` carries `isolation: "worktree"`, so its edits land in a separate
    checkout. The child's final message is its report.
  - Any other member (pi, codex, cursor) is a `Bash` call with `run_in_background: true`: its
    headless command, brief on stdin, report on stdout. It edits this checkout. Don't poll it.
    Wait for the completion notification.
  - Then run each call's `record` line with `--exit` set to the child's exit code (0 for an
    `Agent` that returned), per [sstack § Delegation](../SKILL.md#delegation).
  - An OMC `executor`, a team, or any other spawn tool is not a substitute for the payload.
- `--via headless` blocks until the child ends, up to `[dispatch] timeout_min`: past the
  Bash tool's 10-minute cap. Run it with `run_in_background` and wait for the
  notification.
- Long test/build output: redirect to a file under `.sstack/runs/<run-id>/`.
- No built-in browser, device or capture tool: run the repo's e2e or mobile runner from the shell
  (e.g. `maestro test`; no runner → report the device check as a gap). Capture a browser or
  device still/video: the active ADE's note, else
  [testing.md § Capture with the shell](../../work/testing.md#capture-with-the-shell).
