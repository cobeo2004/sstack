# Refactor

You own the contract. The structure changes; the behaviour does not. A missing
feature or real bug found on the way is split out, not folded in.

1. Pin the behaviour first: `how` to learn the contract, then a characterization
   test, snapshot or equivalence harness capturing current behaviour. Typecheck
   and lint are not a pin. The pin goes in the answer key as protected.
2. Name the structure the code is missing (principle model-the-domain) and the
   target shape: module layout, types, call graph as if built today. The reshape
   must delete branches or invalid states, not add indirection.
3. Subtract before adding: delete dead code, collapse one-caller wrappers, remove
   orphan references (principle laziness).
4. Plan in small behaviour-preserving steps, each keeping the pin green. For API
   reshapes, migrate every caller and delete the old API in the same wave; no
   shims, no parallel old and new paths. (Phase 1 gate.)
5. Implement (Phase 2). Spot-check every rename against the files, including
   strings and docs.
6. Prove behaviour is unchanged on the real artifact; for larger moves, an
   equivalence check (old vs new output diff, or a replayed baseline).
7. Keep it only if the diff lowers reader load somewhere; otherwise revert.
8. Commits: subtraction, then reshape, then cleanup. `review`, then Phase 4.

**Reply:** the structure that changed, the pin, the equivalence proof, what shipped
and what was reverted. No new behaviour.
