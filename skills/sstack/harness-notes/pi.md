# pi

| Generic verb | pi |
|---|---|
| ask the user | ask in chat and stop the turn |
| plan gate | write the plan, then stop and wait for an explicit "yes" in chat |
| todo list | a checklist at `.sstack/runs/<run-id>/todo.md` (uncommitted), playbook steps verbatim |
| spawn a native subagent | not assumed; routed roles use `dispatch` ([sstack](../SKILL.md#delegation)) |
| drive a browser | the active ADE's note; else no built-in browser; the repo's e2e runner or headless Playwright from the shell, else a gap |
| drive a device | the active ADE's note; else the repo's mobile runner (e.g. `maestro test`) or the `agent-device` CLI from the shell, else a gap |
| post-edit hook | symlink `<sstack>/defaults/hooks/pi-sstack.ts` into `~/.pi/agent/extensions/`: on `edit`/`write` it runs `sstack-hook post-edit --harness pi` and marks a failing `check` as `isError` (the installer prints the line) |
| end-of-session hook | the same extension, on `session_shutdown` → `sstack-hook session-end --harness pi`; no session file (`--no-session`) → run `reflect` by hand |

- Headless child: `pi -p --no-session --model <provider/model> --thinking <level>`.
  Read-only roles add `--tools read,grep,find,ls`.
- Model ids are `provider/model`, the same string pi's T3 provider uses, e.g.
  `opencode-go/deepseek-v4.1-flash`. Check with `pi --list-models`.
- pi reads `~/.pi/agent/AGENTS.md` and skills from `~/.pi/agent/skills/`.
- Capture a browser or device still/video: the active ADE's note, else
  [testing.md § Capture with the shell](../../work/testing.md#capture-with-the-shell).
