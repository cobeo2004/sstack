# Model the domain

Encode the real domain in a data structure instead of scattering it across
conditionals. The right structure makes invalid states unrepresentable and deletes
branches. Cheap at write time; a refactor later.

Reach for:
- a state machine instead of scattered booleans or phase checks;
- a typed model instead of loose parameters and repeated shape assumptions;
- a map, registry, table or discriminated union instead of branching across files;
- a reducer or command/event model instead of ad hoc mutation;
- a module owning one body of domain knowledge, not a load/validate/save sequence;
- the collection the access pattern calls for (queue, index, tree, graph).

Don't force it: boring code is fine when the shape is clear, local and won't grow.
Distrust an abstraction that adds indirection without removing branches or
invalid states.

Signs you skipped this: a feature that adds one more `else if`; a second boolean
that must stay in sync with the first; phase-named modules repeating the same rules.

Source: pstack `principle-model-the-domain` @ 91ab921 (MIT).
