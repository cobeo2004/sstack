# claude

Active in bare Claude Code (`CLAUDECODE` is set) when no other ADE matches: T3, Orca
and Conductor run Claude Code too, and win. `sstack-dispatch ade` returns this note.

## Delegation

The payload's calls are the way to start a child. Make each call as given, in one
message when there are several.

- A Claude member is an `Agent` call (`subagent_type: general-purpose`). Read-only
  roles get no isolation; `implement` carries `isolation: "worktree"`, so its edits
  land in a separate checkout. The child's final message is its report.
- Any other member (pi, codex, cursor) is a `Bash` call with `run_in_background: true`:
  its headless command, brief on stdin, report on stdout. It edits this checkout.
  Don't poll it. Wait for the completion notification.

Then run each call's `record` line with `--exit` set to the child's exit code (0 for
an `Agent` that returned). See
[sstack § Delegation](../../skills/sstack/SKILL.md#delegation).

An OMC `executor`, a team, or any other spawn tool is not a substitute for the payload.

## Browser

None built in. Run the repo's e2e runner or headless Playwright from the shell.

## Device

None built in. Use the repo's mobile runner from the shell (e.g. `maestro test`);
with no runner, report the device check as a gap.

## Capture

Capture per [testing.md](../../skills/work/testing.md#capture-with-the-shell) and copy each
file into the run's `media/` folder.
