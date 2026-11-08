# Epistemics for `why`

Code shows what it does, not why it exists. The why lives in commits, PRs,
tickets, docs and conversations: incomplete, biased, sometimes missing. Don't
flatten that into false certainty.

## Confidence tiers

Every claim sits in one tier; the tier sets where it goes and how it's phrased.

1. **Direct** — an author wrote why (PR body, ticket, code comment, design doc,
   chat message). "This exists because X [cite]."
2. **Supported** — several indirect pieces converge. "The evidence points strongly
   to X: [each piece, cited]."
3. **Inferred** — your reading of the context; nothing states it. "Given A and B,
   C seems likely because D."
4. **Speculative** — plausible, thin evidence, other explanations fit. "One
   possibility is X, but there is no direct evidence." Goes in hypotheses.
5. **Unknown** — you looked and couldn't find it. Say exactly what you searched,
   where, and with which terms.

## Phrasing

- Words that claim intent or outcome ("because", "the reason is", "was designed
  to", "fixes", "the team decided") need a citation right next to them. Never use
  them for inferences.
- Hedges for interpretation: "appears to", "likely", "suggests", "is consistent
  with", "may have been".
- Avoid "obviously", "clearly", "of course", "just", "I think".

## Human decisions

When the exact scope of someone's ruling matters, find their original words
(source, speaker, enough wording to show scope). An agent's summary of a ruling is
an interpretation; several notes repeating it are one chain, not independent
evidence.

## Traps

- **Rationalization:** don't retrofit a clean reason onto messy history; a
  consistent pattern may be copy-paste. Absence of evidence isn't evidence of
  absence.
- **Sycophancy:** the user's guess is a candidate to test, not to confirm.
- **Recency bias:** the latest commit isn't the origin.
- **Contradictions:** show both sources; let the user decide.
- **No gaps listed** is suspicious. An honest "we don't know, ask <person>" is a
  valuable answer.

Source: pstack `why/references/epistemics.md` @ 91ab921 (MIT).
