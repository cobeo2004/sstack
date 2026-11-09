# Review lenses

Give every reviewer all of these. Each finding still needs a run that proves it.

1. **Correctness** — wrong results, unhandled states, off-by-one, error paths that
   swallow failures, races between concurrent writers.
2. **Breaks something elsewhere (blast radius)** — trace callers, but go where grep
   stops: wire formats, JSON an API returns, DB columns, feature flags, another
   language reading the same bytes, teardown and ordering. Find the one fact the
   change is safe because of, and try to falsify it with a script.
3. **Developer experience** — changes to how secrets/env vars are read, ports,
   new required setup steps, broken local build or test commands.
4. **Feature leaks** — gated or internal-only behaviour reachable without the gate.
5. **Security** — injection, auth/permission checks, secrets in code or logs,
   unsafe deserialization, path traversal, SSRF.
6. **Tests** — does each new test fail if the behaviour breaks and survive an
   internal refactor (principle test-behavior-not-implementation)? Were protected
   tests edited?
7. **Intended breakage** — if the PR's purpose is to remove a safeguard and the
   scope is tight, don't report it, unless the author likely misjudges the impact.
8. **Compliance** — the rules this repo already wrote down: `AGENTS.md`/`CLAUDE.md`
   from the root down to the touched paths, a CODING_STANDARDS.md, the ADRs, and
   the practice skills the dispatcher listed. Each finding cites what it breaks:
   the rule as `file:line`, the nearest exemplar that does it right, or the `R#` in
   `decisions.md`/`plan.md` that is unmet, over-built or out of scope. **No
   citation, no finding** — an opinion about style is not a compliance finding.

How sure (say where each key claim stopped): said so < pointed at `file:line` <
walked the failure and it can't happen < **ran it** < reproduced in the running app.
