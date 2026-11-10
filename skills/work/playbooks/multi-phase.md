# Multi-phase

Work that spans several PRs (a migration, a large feature). The plan is
the deliverable of the first pass; don't implement until it's approved.

1. One or two files with an obvious approach → skip this playbook, use `feature`.
2. Settle open questions by prototype, not by asking, unless it's a product or
   preference call no run can settle.
3. Recon via `swarm` (role `scout`): each child returns file pointers,
   conventions, test commands, entry points. No dumps.
4. Write `plan.md` with one section per PR, in dependency order. Each section:
   goal; files it may touch (file boundaries); answer key (commands + protected
   tests); live check on the real surface; perf check if it touches a hot path;
   which PRs it depends on.
5. `review` the plan (role `review`) for gaps and ordering; fix what reproduces.
6. **The gate after `plan`.** Stop with the plan path. Execution starts on the user's go.
7. Then run each PR as its own `work` run (feature / refactor / bug-fix playbook),
   in order, each with its own chain of steps and gates. A PR is verified only when its answer key,
   live check and (if any) perf check all pass.

**Reply:** plan path, PR order, what each PR proves, open decisions.
