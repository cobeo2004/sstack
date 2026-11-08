# Prove it works

Verify every output by checking the real thing, not a proxy, a self-report or
"it compiles".

**Why:** unverified work has unknown correctness. Acting on a wrong inference costs
far more than checking the source.

- Read the actual value or state, not a cached or derived copy.
- Check liveness directly (the process, the endpoint), not through a side effect.
- Before reporting success (merged, sent, started, passing), read the real state
  and the exit code. A truncated tail or your own echo proves nothing.
- When a check fails, suspect the observation method before the system.
- Red is a colour, not a measurement: quote the assertion's diff, not the
  assertion. A failure proves the test only when it fails for the reason you
  predicted.
- Verify the process too. For each fact you relied on, name where it came from.
- Strongest proof: a small script that re-runs the comparison. Keep its output so
  a reviewer can re-run it instead of trusting you.

Source: pstack `principle-prove-it-works` @ 91ab921 (MIT).
