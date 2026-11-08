# Test behaviour, not implementation

A test is a claim about what the code does for its users: return values, errors,
state they can read back, effects outside the code (a request sent, a row
written). Private helpers and internal call order are implementation.

Judge each test against two imagined edits:
- **Break the behaviour** (wrong value, skipped or doubled effect). If the test
  still passes it proves nothing. Usual causes: assertion looser than the
  contract, expected value computed by the code under test, asserting on data the
  test built itself.
- **Change the internals** but keep every observable result. If the test fails, it
  is pinned to the implementation and will need rewriting on every refactor.

Keep tests that catch the first and survive the second. Drive the code through its
users' interface with concrete input; derive the expected value from the
requirement, not from a run of the code.

The contract decides: the payload a mocked external service receives is
behaviour; a call to an internal helper is not. Pair "no call happened" with a
case where it does, so the test shows it can see a call. Error types callers
branch on are contract; exact messages usually aren't.

Source: pstack `principle-test-behavior-not-implementation` @ 91ab921 (MIT).
