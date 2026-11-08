# Cursor (agent / cursor-agent)

| Generic verb | Cursor |
|---|---|
| ask the user | ask in chat and stop the turn |
| plan gate | Plan mode if the session has it; otherwise write the plan and wait for "yes" |
| todo list | the agent's built-in todo list |
| spawn a native subagent | not assumed; use `<sstack>/bin/sstack-dispatch`, or do the role here when it prints `local` |
| drive a browser | the ADE's tools first ([ade.md](ade.md)); else Cursor's built-in browser tool if enabled; else the repo's e2e runner from the shell |
| drive a device | the ADE's tools first ([ade.md](ade.md)); else the repo's mobile runner (e.g. `maestro test`) from the shell |
| end-of-session hook | none assumed; run `reflect` by hand at the end of a task |

- Headless child: `cursor-agent -p --force --model <m>`. It has no read-only mode
  in `config.example.toml`, so dispatch refuses read-only roles (scout,
  investigate, plan, review) on cursor. Route those to another harness.
- Skills load from `~/.cursor/skills/` (`sstack-install` links it if it exists).
