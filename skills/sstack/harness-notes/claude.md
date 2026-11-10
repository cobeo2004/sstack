# Claude Code

| Generic verb | Claude Code |
|---|---|
| ask the user | `AskUserQuestion` (one question, 2–4 options); plain chat if unavailable |
| plan gate | `EnterPlanMode` to draft, `ExitPlanMode` for the user's approval |
| todo list | `TaskCreate`/`TaskUpdate`, or `TodoWrite` where configured |
| spawn a native subagent | `Agent(...)` — only for local roles; routed roles use `dispatch` ([sstack](../SKILL.md#delegation)) |
| drive a browser | the active ADE's note; else an MCP browser tool or browser skill the session has (e.g. Playwright MCP); else headless Playwright from the shell |
| drive a device | the active ADE's note; else the repo's mobile runner (e.g. `maestro test`) from the shell |
| post-edit hook | `PostToolUse` matcher `Edit\|Write` in `~/.claude/settings.json` → `<sstack>/bin/sstack-hook post-edit --harness claude`; a failing `check` (exit 2) is fed back (the installer prints the snippet) |
| end-of-session hook | `SessionEnd` hook in `~/.claude/settings.json` → `<sstack>/bin/sstack-reflect-hook` (the installer prints the snippet) |

- Headless child: `claude -p --model <m>`; read-only roles use
  `--permission-mode plan` (set in `~/.sstack/harnesses/claude.toml`, synced from the template).
- Long test/build output: redirect to a file under `.sstack/runs/<run-id>/`.
- Capture a browser or device still/video: the active ADE's note, else
  [testing.md § Capture with the shell](../../work/testing.md#capture-with-the-shell).
