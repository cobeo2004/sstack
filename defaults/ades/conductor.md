# conductor

Active when `CONDUCTOR_SESSION_ID` is set.

## Delegation

Unverified: the hook below is tested on fakes only, until the `sstack-doctor --smoke`
run.

Dispatch runs `conductor.hook` over the Conductor CLI/API. Without
`CONDUCTOR_API_KEY` the hook returns `none`, and dispatch runs the member headless
with that note. The agent does not call the API itself. A hook that hands back a
tool payload exits `4`: follow
[sstack § Delegation](../../skills/sstack/SKILL.md#delegation).

## Browser

The in-app browser (⌘⇧B) is for the **user**: they watch the page and annotate it
for the agent; the agent cannot drive it.

For an agent check, run the repo's e2e runner or a short headless Playwright
script from the shell. Serve on `$CONDUCTOR_PORT` so parallel workspaces do not
collide. Save screenshots under the run dir and tell the user the URL to open
with ⌘⇧B.

## Device

None built in. Use the repo's mobile runner from the shell (e.g. `maestro test`);
with no runner, report the device check as a gap.

## Capture

Use Playwright: `page.screenshot({ path })` for stills and
`recordVideo: { dir }` on the browser context for video. Copy the files into the
run's `media/` folder.
