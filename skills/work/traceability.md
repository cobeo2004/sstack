# Requirements, ADRs and the glossary

How `work` ties a change to numbered intent and to the decisions the repo already
made. `grill` writes `R1..Rn` in `decisions.md`; this file says what reads them.

## Every R# is traced

- `plan.md`: every step cites the `R#` it serves, and names the check that proves
  it. A step serving no requirement is out of scope — drop it or say so.
- `answer-key.md`: every check cites the `R#` it proves.
- **The gate after the `plan` step:** a requirement no check covers, or a check
  proving no requirement, blocks it. Report both lists and fix them before asking for the yes.
- No `decisions.md` (no `grill`) → the requirements are the task's own bullets,
  numbered the same way in `plan.md`.

## Recon reads the decisions the repo already made

In the `recon` step, for the area the task touches:

- **ADRs** — `docs/adr/`, `docs/decisions/`, `docs/architecture/decisions/`, or
  `*.adr.md`; also a root `DECISIONS.md`. Read the ones whose title names this
  area or the mechanism being changed.
- **A plan that contradicts an ADR says so**: which ADR, how it conflicts, and
  whether the user wants to supersede it. `work` never writes or edits an ADR.
- **The glossary** — the file `setup` linked in `.sstack/product.md` (`CONTEXT.md`,
  `GLOSSARY.md`, `docs/glossary*`). Read the entries for the touched area; a plan
  that renames or redefines one of them names that change out loud.

## Settled terms go back to the glossary

When a decision or the implementation settles on a term, add it to that existing
glossary: one definition, then `_Avoid_:` with the words that mean something else
here. No glossary in the repo → skip it and say so once; never create an empty one.

The `review` step re-reads the answer key against `plan.md`: a requirement whose
scope moved mid-flight, or one the diff silently dropped, is reported before that
step's gate.
