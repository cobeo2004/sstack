# Fix root causes

Fix the fault, not the place it surfaced. The root cause is the first place the
system did something it shouldn't, or failed to handle a state it should.

**Why:** a symptom fix hides the evidence and leaves the fault free to surface
elsewhere, with a workaround nobody named.

- Reproduce first.
- Ask "why" until the answer is a wrong decision in code, not a consequence.
- Stuck → instrument. Read the actual error and state. Don't guess.
- Is the triggering state legitimate? If yes, the code that broke on it is the
  cause; handle it there. If it should never exist, find what produced it.
  Guards, retries, swallowed errors and clamped values are how bugs hide.
- Fails only after a restart → suspect persisted state (config, cache, locks).
- Fix the pattern, not the instance: find every place with the same fault.
- A workaround that needs a paragraph to justify it means the code is wrong.
- If the deciding fact took a deep dig, propose the cheap always-on signal that
  would have shown it at first look.

Source: pstack `principle-fix-root-causes` @ 91ab921 (MIT).
