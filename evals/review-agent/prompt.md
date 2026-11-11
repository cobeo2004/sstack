---
description: "Bare Claude Code at the review step: a read-only Agent (no isolation) from the review payload."
tags: [dispatch, session, readonly]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, Skill, Agent]
---
Use the work skill to continue the run in .sstack/runs/subtract-1. Implement and gate are done; the next step is review. Do that step, record it with sstack-workflow, and stop at the next gate.
