# Cursor (agent / cursor-agent)

| Generic verb | Cursor |
|---|---|
| ask the user | ask in chat and stop the turn |
| plan gate | Plan mode if the session has it; otherwise write the plan and wait for "yes" |
| todo list | the agent's built-in todo list |
| spawn a native subagent | not assumed; routed roles use `dispatch` ([sstack](../SKILL.md#delegation)), or do the role here on exit `3` |
| drive a browser | the active ADE's note; else Cursor's built-in browser tool if enabled; else the repo's e2e runner from the shell |
| drive a device | the active ADE's note; else the repo's mobile runner (e.g. `maestro test`) from the shell |
| end-of-session hook | none assumed; run `reflect` by hand at the end of a task |

- Headless child: `cursor-agent -p --force --model <m>`; read-only roles use
  `--mode plan` (set in `<sstack>/defaults/harnesses/cursor.toml`).
- Skills load from `~/.cursor/skills/` (`sstack-install` links it if it exists).
- Capture a browser or device still/video: the active ADE's note, else
  [testing.md § Capture with the shell](../../work/testing.md#capture-with-the-shell).
