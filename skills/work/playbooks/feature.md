# Feature

You own the design. Plan, review, verify. Implementation may be routed.

1. `how` over the affected subsystem (step `recon`).
2. Name the data shape first and its organizing structure (principle
   model-the-domain): state machine over booleans, table over branching, typed
   model over loose parameters.
3. Write the throughput check as four todo items (`n/a: <reason>` if one doesn't
   apply): blocking first steps; independent workstreams; shared mutable state
   (split it, per separate-before-serializing-shared-state); smallest safe
   decomposition (one implementer is usually right; say why).
4. Plan and answer key (step `plan`); stop at its gate for the yes.
5. Implement by dispatching `implement` (see [sstack § Delegation](../../sstack/SKILL.md#delegation))
   with a specific scope: file paths, the data shape, success criteria (step `implement`).
6. Verify on the real surface (run the app, call the API). "Inconclusive" or the
   wrong surface is not a pass.
7. `review` the diff; resolve findings (the gate after the `review` step).
8. `pr`: `unslop`, user's yes, PR, `babysit`.

**Reply:** what you built, the shape you chose and why, how you verified it, open
decisions.
