# Perf

You own the measurement. Tie every fix to a number; don't read source instead of
measuring.

1. Capture a baseline on the real surface. Record the environment, the workload,
   and whether each run is **cold or warm**. Repeat and alternate comparable runs;
   measure the noise floor. A difference within noise is **inconclusive**, not a win.
2. State, before expensive runs, which result would change the decision.
3. `how` to ground hypotheses. Try the cheapest first and stop when one meets the
   target: don't do it; don't do it again; do it less; do it later; do it when
   they're not looking; do it concurrently; do it cheaper.
4. Plan the fix from the measurement; the benchmark command and its threshold go
   in the answer key (Phase 1 gate).
5. Implement one attempt at a time and measure each before the next (Phase 2).
6. Post-fix measurement under the same conditions. Compare the artifacts, not
   impressions. Wrong surface or mixed cold/warm runs is not a pass.
7. `review`, then Phase 4; cite the numbers in the PR.

**Reply:** baseline, post-fix number, delta with noise floor and units, run count,
cold/warm, artifact path.
