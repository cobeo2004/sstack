# ADE notes: built-in browser and device

The app the agent runs in (the ADE) decides which browser and device the agent
can drive for its live self-check ([work/testing.md](../../work/testing.md)).
Detect it first, then use its tools. Fall back to the harness note only when the
ADE has nothing the agent can drive.

| ADE | Detect | drive a browser | drive a device |
|---|---|---|---|
| T3 Code | `T3CODE_THREAD_ID` is set | the `preview_*` tools | the `device_*` tools |
| Orca | `command -v orca` and `orca status --json` succeed | `orca goto / snapshot / click / fill / screenshot / console` | `orca emulator …` (iOS Simulator) |
| Conductor | `CONDUCTOR_SESSION_ID` is set | none the agent can drive: headless runner from the shell | none: shell runner, or a gap |
| None of these | — | the harness note's row | the harness note's row |

The two rows below are what the skill lint checks for; they summarise the table.

| Generic verb | Rule |
|---|---|
| drive a browser | the ADE's browser tools above; else the harness note's browser row |
| drive a device | the ADE's device tools above; else the harness note's device row |

## T3 Code

- **Browser:**
  1. `preview_open` the dev server URL.
  2. `preview_navigate`, `preview_act` (click, type), `preview_wait_for`.
  3. Assert with `preview_snapshot`. Use `preview_evaluate` for console or DOM reads, and `preview_resize` for mobile widths.
  4. Close the tab you opened.

  The user watches it in the preview panel.
- **Device:**
  1. `device_list`.
  2. `device_open` with its `hostId` and `id`. It returns an `agent-device` command; run that command for every launch, tap, text entry and deep link.
  3. `device_screenshot` to look.
  4. `device_close` when done.

  Builds and installs still go through the shell (`xcrun simctl install`, `adb install`). Drive the screen only through `agent-device`.
- **Capture:**
  - Browser screenshot: `preview_snapshot` with `save=true`, which returns `screenshotPath`.
  - Browser video: `preview_recording_start`, then `preview_recording_stop`, which returns the file path (50 MiB max).
  - Device screenshot: `device_screenshot`.
  - Device video: the `agent-device` command's recording (see its `help`).

  Copy each file into the run's `media/` folder.
- **Delegate a role.** `sstack-dispatch`'s own thread transport (`t3 thread start`)
  makes a top-level thread with no parent and drops effort. With the T3 tools
  loaded, take the route and start the children yourself:
  1. `sstack-dispatch <role> --route [--hint <kind>] [--files …]` prints
     `{role, route, readonly, members: [{harness, provider, model, effort, options}]}`.
     Exit `3` with `members: []` → run the role here. Exit `1` → config error, stop.
  2. One `delegate_task` per member: `target = {providerInstanceId: provider,
     model, options}`, `role` = `implementation` / `review` / `research`, and
     `interactionMode: "plan"` when `readonly`. Children are linked to this thread
     and honour `options` (effort).
  3. The parent writes the child's summary to the run's `--report` path and records
     the run; a child's final message is not the report until you have read it.
  Plan mode is an instruction to the child, not a sandbox: for a read-only role, take `git status --porcelain` before and after
  and append the working-tree warning headless dispatch would write.
- If the tools aren't loaded, search the deferred tool list for `preview` or `device`.

## Orca

- **Setup:** the `orca-cli` skill teaches the commands (`orca skills get <topic>`). If it isn't installed, ask before running `orca skills install --skill orca-cli`.
- **Browser** (add `--worktree active --json` to each command):
  1. `orca goto --url <url>`.
  2. `orca snapshot` gives element refs like `@e3`. Act on them with `orca click --element @e3` and `orca fill --element @e1 --value "…"`, and use `orca wait --text "…"`.
  3. Collect evidence with `orca screenshot`, `orca console --limit 50` and `orca network --limit 50`.
- **Device** (iOS):
  1. `orca emulator list --json`, then `orca emulator attach "<device>" --json`.
  2. `orca emulator tap <x> <y>` (coordinates normalized 0–1), `orca emulator type "…"`, `orca emulator button home`.
  3. Get screenshots per the `orca-emulator` skill.
  4. Android: the `orca-emulator-android` skill (adb-based).
- **Capture:** `orca screenshot` (browser) and `orca full-screenshot`. Orca's docs
  don't cover video or emulator screenshots, so take a screenshot per step and
  skip the recording, or record with the shell fallback below.

## Conductor

- Its in-app browser (⌘⇧B) is for the **user**: they can watch the page and annotate it for the agent. The agent can't drive it.
- **Browser check:** run the repo's e2e runner, or a short headless Playwright script, from the shell. Serve on `$CONDUCTOR_PORT` so parallel workspaces don't collide. Save screenshots under the run dir and tell the user the URL to open with ⌘⇧B.
- **Device:** none built in. Use the repo's mobile runner from the shell (e.g. `maestro test`); with no runner, the device check is a gap.

## Shell capture (outside T3 Code)

- **Playwright:** `page.screenshot({ path })`; video via `recordVideo: { dir }` on the browser context.
- **iOS Simulator:** `xcrun simctl io booted screenshot <file>` and `xcrun simctl io booted recordVideo <file>` (Ctrl-C to stop).
- **Android:** `adb exec-out screencap -p > <file>` and `adb shell screenrecord /sdcard/flow.mp4`, then `adb pull`.

