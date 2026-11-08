# Separate before serializing shared state

When concurrent actors might share mutable state, first ask whether they need the
same object at all. Usually they don't: eliminate the sharing.

**Why:** concurrent writes create races that are intermittent and expensive to
debug. Instructions and conventions are not concurrency control.

1. Identify shared mutable state: files both write, branches both push, the
   working tree two children edit.
2. Default: give each actor its own file, key, branch or directory, and merge only
   when reading or reporting. (sstack: each panel member writes its own report;
   only one `implement` child edits the tree at a time.)
3. Only when one shared target is a real invariant, serialize structurally:
   sequential phases, a single writer, a lockfile, compare-and-swap. "We need a
   lock" is a smell to check, not the default.

Source: pstack `principle-separate-before-serializing-shared-state` @ 91ab921 (MIT).
