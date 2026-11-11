---
type: tool_used
tool: Bash
input_match: 'sstack-dispatch (record implement|implement[^"]*--via local)'
min: 1
---
Either the Agent child ran and `record` closed it, or (no worktree isolation, as in the eval
harness) the agent took the sanctioned `--via local` fallback instead of skipping the dispatch.
