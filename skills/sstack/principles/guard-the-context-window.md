# Guard the context window

Context that fills up degrades reasoning, causes compression artifacts and stalls
progress. Spend it on decisions, not raw data.

- Size phases and cap scope: limit files per phase; budget turns.
- Redirect long output (test logs, builds) to a file and read the tail or grep it.
- Read the part of a file you need, not the whole file, when you know where it is.
- Route bulk reading to children (`swarm`, role `scout`) once a question needs
  about five or more sources; keep their summaries, not their dumps.
- Write state that must survive (plan, answer key, progress) to
  `.sstack/runs/<run-id>/`, not only to conversation memory, so a compaction or a
  new session can resume.

Source: pstack `principle-guard-the-context-window` @ 91ab921 (MIT).
