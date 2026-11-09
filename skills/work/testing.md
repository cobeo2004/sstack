# Testing by surface

How a check is written, run and proven. `work` uses this in Phase 0 (test
strategy), Phase 1 (answer key) and Phase 3 (run). `setup` records each surface's
commands in `[project.test]`. Read principle test-behavior-not-implementation
before writing any test.

## Two layers, every time

1. **Code tests** prove the logic, and they're repeatable in CI.
2. **A live self-check** proves the user-facing result. The agent drives the real
   app in the ADE's built-in browser or device and checks it, the way a person
   would. This is required for any change a user can see: a page, a screen, a
   flow. Green unit tests never stand in for it.

An API change gets code tests plus a real call to the running endpoint. A pure
library change gets code tests only.

Tag each answer-key check with its surface: `code:`, `browser:` or `mobile:`.
Never add a framework, dependency or device setup without the user's yes at the
plan gate.

## Find the browser and device

Use the ADE you're running in first, then the harness's own tool, then the
shell. The tools for T3 Code, Orca and Conductor are in
[harness-notes/ade.md](../sstack/harness-notes/ade.md). The harness fallbacks
are in the harness notes ("drive a browser", "drive a device"). Say in the
report which one you used.

## Code

**Write.** Use the repo's framework and conventions (`[project.test.code]`): same
folder layout, file naming, fixtures and helpers as the nearest existing test.
One behaviour per test, concrete input, expected value taken from the
requirement. For a feature or bug fix, write the test first and watch it **fail
for the right reason**: the missing behaviour, not an import error. For a bug
fix, the test reproduces the reported failure.

**Run.** Narrow first (`run` with the test's path or name), then the whole suite
(`[project].verify`). Redirect long output to `.sstack/runs/<run-id>/`.

**Proof.** The command, plus pass/fail counts and the decisive assertion, trimmed.
New tests show RED then GREEN. A test that passed before the change proves
nothing about it.

## Browser (live self-check)

**Write** a scripted check in `answer-key.md` before implementing. Include:
- the start URL;
- numbered steps (navigate, click, type), named by what the user sees (labels, roles, text), not by CSS internals;
- the expected visible state after each key step;
- for responsive work, the viewport widths.

It must be precise enough that two runs agree.

If the repo has an e2e runner (`[project.test.browser]`), also add a spec beside
the existing ones, so CI repeats the check.

**Run.**
1. Start the app with `serve` and wait until `url` responds.
2. In the ADE's browser, follow the steps and confirm each expected state.
3. Read the console and failed network requests.
4. Run the e2e spec headless if you wrote one.
5. Stop the server and close any tab you opened.

**Proof.** Each step's outcome and a screenshot of the final state, saved under
`.sstack/runs/<run-id>/`. Add "console clean" or the errors found, plus the
runner's result if there's a spec. "Page loaded" is not a pass; only the
expected state is.

## Mobile (live self-check)

**Write** a scripted check in `answer-key.md`. Include:
- the platform (iOS or Android) and device;
- the app state at the start (fresh install, logged in);
- the steps, named by accessibility labels and visible text;
- the expected screen after each key step.

If the repo has a mobile runner (Maestro, Detox, etc., per
`[project.test.mobile]`), also add a flow beside the existing ones.

**Run.**
1. Build and install with `build` on the named platform.
2. In the ADE's device panel, launch the app, follow the steps and confirm each expected screen. A deep link is fine to reach the starting screen; drive the behaviour under test through the UI.
3. Run the runner's flow if you wrote one.

**Proof.** Each step's outcome, a screenshot of the final screen under
`.sstack/runs/<run-id>/`, the platform and device, and the runner's result if
there's a flow.

## Before / after evidence

Any change a user can see ships with before/after media for the PR. A backend
change (API, service, job, data flow) ships with diagrams instead; see
[Backend diagrams](#backend-diagrams).

1. **After:** while running the live self-check on the change, save a screenshot
   at each key step as `.sstack/runs/<run-id>/media/after-<step>.png`. Record
   the whole flow as `after-flow.mp4` (or `.mov`/`.webm`).
2. **Before:** run the same scripted check on the base commit, in a throwaway
   worktree, so your tree isn't touched:
   1. `git worktree add .sstack/runs/<run-id>/base <base-sha>`.
   2. Install and serve it there, on another port if needed.
   3. Save `before-<step>.png` (and `before-flow.mp4` for a bug, to show it).
   4. `git worktree remove .sstack/runs/<run-id>/base`.

   A brand-new screen has no before; say so instead.
3. Use the same `<step>` names on both sides; matching names become one table
   row. The ADE's capture tools are in
   [harness-notes/ade.md](../sstack/harness-notes/ade.md).
4. Look at every image before publishing. Crop out or skip any frame that shows
   secrets, tokens or personal data.

Publishing happens in Phase 4, with the user's yes, right after opening the PR:
`<sstack>/bin/sstack-pr-media <pr> <run>/media/* --edit-body` pushes the files to
the repo's `sstack-media` branch (never the PR branch) and puts the marked
Before | After table in the PR description. PR comments are only for add-ons
(media captured after review, follow-up notes), never the main evidence.

### Backend diagrams

For a change in how requests, jobs or data move, draw the flow as Mermaid from the
code (the `diagram` skill's Mermaid fallback; `how` for the facts):

- `media/before-<flow>.mmd` from the base commit and `media/after-<flow>.mmd` from
  the change. Use a `sequenceDiagram` for calls between services, a `flowchart`
  for branching logic, a `stateDiagram-v2` for status changes, an `erDiagram` for
  schema changes. A brand-new flow has only `after`.
- Each node and arrow is a real function, endpoint, queue or table you can cite;
  no invented boxes. Keep it under about 15 nodes: the part that changed.
- Add the proof beside it: the endpoint call or test output from Phase 3.

`sstack-pr-media` puts `.mmd` files in the same Before | After table as images,
as ```` ```mermaid ```` blocks (GitHub renders them), and doesn't push them. A PR
with only diagrams needs no media branch.

## When a check can't run

No browser or device the agent can drive, no simulator installed, the service
won't start: say exactly which check didn't run and why. It's a gap in the
report, never a pass. Offer the smallest way to close it, such as a device, a
runner, or a command the user can run while watching.
