---
description: "Control: implement has max_agents = 0, so the agent does it in this session and spawns nothing."
tags: [control, inline]
max_turns: 40
timeout_seconds: 900
allowed_tools: [Bash, Read, Write, Edit, Glob, Grep, Skill, Agent]
---
Use the work skill to continue the run in .sstack/runs/subtract-1. The plan gate is approved; the next step is implement. Do that step, record it with sstack-workflow, and stop at the next gate.
