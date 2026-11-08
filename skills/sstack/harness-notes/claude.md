# Claude Code

| Generic verb | Claude Code |
|---|---|
| ask the user | `AskUserQuestion` (one question, 2–4 options); plain chat if unavailable |
| plan gate | `EnterPlanMode` to draft, `ExitPlanMode` for the user's approval |
| todo list | `TaskCreate`/`TaskUpdate`, or `TodoWrite` where configured |
| spawn a native subagent | `Agent(...)` — only for local roles; routed roles go through `<sstack>/bin/sstack-dispatch` |
| drive a browser | the ADE's tools first ([ade.md](ade.md)); else an MCP browser tool or browser skill the session has (e.g. Playwright MCP); else headless Playwright from the shell |
| drive a device | the ADE's tools first ([ade.md](ade.md)); else the repo's mobile runner (e.g. `maestro test`) from the shell |
| end-of-session hook | `SessionEnd` hook in `~/.claude/settings.json` → `<sstack>/bin/sstack-reflect-hook` (the installer prints the snippet) |

- Headless child: `claude -p --model <m>`; read-only roles use
  `--permission-mode plan` (set in `config.example.toml`).
- **In T3 Code** (`T3CODE_THREAD_ID` is set): `<sstack>/bin/sstack-dispatch` starts a visible
  T3 thread for non-read-only roles. You may instead use T3's native
  `delegate_task` tool for the configured provider and model — same brief, same
  report contract, effort passed as a provider option. Read-only roles stay
  headless either way.
- Long test/build output: redirect to a file under `.sstack/runs/<run-id>/`.
