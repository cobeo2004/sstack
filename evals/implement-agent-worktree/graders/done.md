---
type: tool_used
tool: Bash
input_match: 'sstack-workflow done implement|sstack-dispatch record implement[^"]*--exit [1-9]'
min: 1
---
Either the step was recorded with `done`, or the child failed, `record` logged that failure, and
the agent stopped there. That stop is correct: a failed dispatch waits for the next gate and is
never redone quietly in the session.
