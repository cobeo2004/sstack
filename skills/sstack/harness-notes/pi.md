# pi

| Generic verb | pi |
|---|---|
| ask the user | ask in chat and stop the turn |
| plan gate | write the plan, then stop and wait for an explicit "yes" in chat |
| todo list | a checklist at `.sstack/runs/<run-id>/todo.md` (uncommitted), playbook steps verbatim |
| spawn a native subagent | not assumed; use `<sstack>/bin/sstack-dispatch` |
| end-of-session hook | none assumed; run `reflect` by hand at the end of a task |

- Headless child: `pi -p --no-session --model <provider/model> --thinking <level>`.
  Read-only roles add `--tools read,grep,find,ls`.
- Model ids are `provider/model`, the same string pi's T3 provider uses, e.g.
  `opencode-go/deepseek-v4.1-flash`. Check with `pi --list-models`.
- pi reads `~/.pi/agent/AGENTS.md` and skills from `~/.pi/agent/skills/`.
