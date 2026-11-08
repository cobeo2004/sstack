# Feature

You own the design. Plan, review, verify. Implementation may be routed.

1. `how` over the affected subsystem (Phase 0).
2. Name the data shape first and its organizing structure (principle
   model-the-domain): state machine over booleans, table over branching, typed
   model over loose parameters.
3. Write the throughput check as four todo items (`n/a: <reason>` if one doesn't
   apply): blocking first steps; independent workstreams; shared mutable state
   (split it, per separate-before-serializing-shared-state); smallest safe
   decomposition (one implementer is usually right; say why).
4. Plan and answer key (Phase 1); get the plan gate.
5. Implement via `<sstack>/bin/sstack-dispatch implement` with a specific scope: file paths,
   the data shape, success criteria (Phase 2).
6. Verify on the real surface (run the app, call the API). "Inconclusive" or the
   wrong surface is not a pass.
7. `review` the diff; resolve findings (Phase 3 gate).
8. Phase 4: `unslop`, user's yes, PR, `babysit`.

**Reply:** what you built, the shape you chose and why, how you verified it, open
decisions.
