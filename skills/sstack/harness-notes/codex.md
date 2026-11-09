# Codex CLI

| Generic verb | Codex |
|---|---|
| ask the user | ask in chat, one question at a time, and stop the turn |
| plan gate | write the plan, then stop and wait for an explicit "yes" in chat |
| todo list | the `update_plan` tool |
| spawn a native subagent | `spawn_agent` then wait, only for local roles; routed roles use `dispatch` ([sstack](../SKILL.md#delegation)) |
| drive a browser | the active ADE's note; else a browser MCP server if configured; else the repo's e2e runner or headless Playwright from the shell |
| drive a device | the active ADE's note; else the repo's mobile runner (e.g. `maestro test`) or the `agent-device` CLI from the shell |
| post-edit hook | `PostToolUse` matcher `apply_patch` in `~/.codex/hooks.json` → `<sstack>/bin/sstack-hook post-edit --harness codex`; needs `hooks = true` under `[features]`; trust the new hook when codex asks (the installer prints the snippet) |
| end-of-session hook | `SessionEnd` in `~/.codex/hooks.json` → `<sstack>/bin/sstack-hook session-end --harness codex` (the installer prints the snippet) |

- Headless child: `codex exec -m <m> -c model_reasoning_effort=<e> -`; read-only
  roles use `--sandbox read-only` (set in `<sstack>/defaults/harnesses/codex.toml`).
- Codex reads `~/.codex/AGENTS.md` and skills from `~/.codex/skills/`
  (`sstack-install` links both).
- Capture a browser or device still/video: the active ADE's note, else
  [testing.md § Capture with the shell](../../work/testing.md#capture-with-the-shell).
