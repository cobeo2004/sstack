# Codex CLI

| Generic verb | Codex |
|---|---|
| ask the user | ask in chat, one question at a time, and stop the turn |
| plan gate | write the plan, then stop and wait for an explicit "yes" in chat |
| todo list | the `update_plan` tool |
| spawn a native subagent | `spawn_agent` then wait, only for local roles; routed roles use `dispatch` ([sstack](../SKILL.md#delegation)) |
| drive a browser | the active ADE's note; else a browser MCP server if configured; else the repo's e2e runner or headless Playwright from the shell |
| drive a device | the active ADE's note; else the repo's mobile runner (e.g. `maestro test`) or the `agent-device` CLI from the shell |
| end-of-session hook | none built in; run `reflect` by hand at the end of a task |

- Headless child: `codex exec -m <m> -c model_reasoning_effort=<e> -`; read-only
  roles use `--sandbox read-only` (set in `<sstack>/defaults/harnesses/codex.toml`).
- Codex reads `~/.codex/AGENTS.md` and skills from `~/.codex/skills/`
  (`sstack-install` links both).
- Capture a browser or device still/video: the active ADE's note, else
  [testing.md § Capture with the shell](../../work/testing.md#capture-with-the-shell).
