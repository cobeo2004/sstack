# Sequence verifiable units

Order work as small units, each ending in a state you can check. Don't advance
until the current one is green.

**Why:** a break caught at the unit that caused it is cheap to find. A break caught
after a batch is buried, and you've built further on a broken base.

- **Execution.** Each unit is a bracket: known-good state, one change, run the
  check, proceed. In sweeps and migrations, verify each edit before the next.
  Start from a clean, current base so checks measure against the real baseline.
- **Delivery.** Stack commits and PRs in the order that proves the work: failing
  test first, then the fix; subtraction before the reshape; baseline before the
  treatment. Each commit stands on its own.

Pairs with prove-it-works (keep each check real).

Source: pstack `principle-sequence-verifiable-units` @ 91ab921 (MIT).
