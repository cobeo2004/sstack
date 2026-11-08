# Bug fix

Be scientific: every shipped line traces to runtime evidence. A change that
"might help" is a hypothesis, not a fix. When evidence refutes a hypothesis,
revert what it motivated.

1. Reproduce it yourself on the surface where it was reported. Ask the user only
   with a specific reason you can't reach it, after going as far as you can. If it
   won't reproduce, synthesize the trigger or add instrumentation until it fires.
2. Binary-search the cause: list hypotheses (seed them with `how`, and `why` for
   regression history), then take the split that rules out the most, get runtime
   evidence, eliminate. Instrument instead of guessing (principle fix-root-causes).
3. Confirm the surviving mechanism with runtime evidence.
4. **Diagnose-only exit:** if the user asked only for the cause, stop here and
   report: symptom, root cause with evidence, proposed fix, what you didn't verify.
5. Plan the fix; the failing repro goes in the answer key as a protected test when
   it's cheap to write (Phase 1 gate).
6. Implement the smallest change the evidence justifies (Phase 2).
7. Verify on the same surface: the original repro now passes. Unit tests show
   branch behaviour, not bug absence.
8. Order commits so the failing test lands before the fix. `review`, then Phase 4.

**Reply:** what was broken, root cause, fix, how you verified it. Quote the
decisive failing and passing output, trimmed to the assertion and counts.
