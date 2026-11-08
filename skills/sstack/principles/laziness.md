# Laziness

Bias to deletion and the smallest change that solves the problem.

- **Minimize the diff.** Fewer lines beat elegant boilerplate. No layer, option or
  abstraction the task doesn't need today.
- **Consolidate decisions.** Make each choice in one place and pass the result as a
  plain value; don't repeat it across files.
- **Reach for what exists:** the standard library, the platform, a dependency the
  repo already has, before writing new code.
- **Subtract first.** Remove dead weight, then build on the simpler base.
- Lazy is not careless: validation at trust boundaries, error handling that
  prevents data loss, and the check that proves the change stay.

Source: pstack `principle-laziness-protocol` @ 91ab921 (MIT).
