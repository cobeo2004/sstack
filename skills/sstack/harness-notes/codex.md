# Codex CLI

| Generic verb | Codex |
|---|---|
| ask the user | ask in chat, one question at a time, and stop the turn |
| plan gate | write the plan, then stop and wait for an explicit "yes" in chat |
| todo list | the `update_plan` tool |
| spawn a native subagent | `spawn_agent` then wait, only for local roles; routed roles go through `<sstack>/bin/sstack-dispatch` |
| end-of-session hook | none built in; run `reflect` by hand at the end of a task |

- Headless child: `codex exec -m <m> -c model_reasoning_effort=<e> -`; read-only
  roles use `--sandbox read-only` (set in `config.example.toml`).
- Codex reads `~/.codex/AGENTS.md` and skills from `~/.codex/skills/`
  (`sstack-install` links both).
