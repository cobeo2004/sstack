# cursor

Ships with auto-detection off. Set `ade = "cursor"` to force it.

## Delegation

`Task` is built in: call it directly, no load step. Read-only calls carry
`readonly: true`, and `record` checks the tree for changes either way. Start, wait,
collect and `record` per [sstack § Delegation](../../skills/sstack/SKILL.md#delegation).

## Browser

Use Cursor's Browser subagent when it is enabled. Otherwise run the repo's e2e
runner or headless Playwright from the shell.

## Device

None built in. Use the repo's mobile runner from the shell (e.g.
`maestro test`); with no runner, report the device check as a gap.

## Capture

Save the Browser subagent's screenshot under the run's `media/` folder. Without
it, capture per [testing.md](../../skills/work/testing.md#capture-with-the-shell).
