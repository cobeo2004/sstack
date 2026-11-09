# orca

Active when `ORCA_AGENT_SESSION_ID` is set.

## Delegation

Unverified: the hook lifecycle below is tested on fakes only, until the
`sstack-doctor --smoke` run.

Dispatch runs the `orca.hook` lifecycle: task-create → worker-start,
`check --wait`, then collect. The hook starts the child and returns its report;
the agent does not call Orca directly. A hook failure falls back to headless
dispatch with a note. A hook that hands back a tool payload exits `4`: follow
[sstack § Delegation](../../skills/sstack/SKILL.md#delegation).

## Browser

Add `--worktree active --json` to each command.

1. `orca goto --url <url>`.
2. `orca snapshot` gives element refs like `@e3`. Act with
   `orca click --element @e3`, `orca fill --element @e1 --value "…"`, and wait
   with `orca wait --text "…"`.
3. Collect evidence with `orca screenshot`, `orca console --limit 50` and
   `orca network --limit 50`.

The `orca-cli` skill teaches the commands (`orca skills get <topic>`). If it is
not installed, ask before `orca skills install --skill orca-cli`.

## Device

iOS:

1. `orca emulator list --json`, then `orca emulator attach "<device>" --json`.
2. `orca emulator tap <x> <y>` (normalized 0–1), `orca emulator type "…"`,
   `orca emulator button home`.
3. Get screenshots per the `orca-emulator` skill.

Android: the `orca-emulator-android` skill (adb-based).

## Capture

`orca screenshot` for the browser and `orca full-screenshot`. For video or
emulator stills, take a screenshot per step or use the shell fallback:
Playwright `recordVideo`, `xcrun simctl io booted recordVideo`, or
`adb shell screenrecord` plus `adb pull`.
