---
name: hermes-main-conflict-detector
description: 'Detect when a new instruction from АЮ contradicts existing ROADMAP, prior instructions in this session, or a constraint in AGENTS.md. Trigger on any new instruction intake by MAIN.'
---

For each new instruction:

1. Read `ROADMAP.md` In Progress and Queued sections.
2. Compare the new instruction against existing items: priority change, scope change, conflicting design choice, contradicted decision, or duplicate ownership.
3. If conflict is found, trigger `hermes-escalate-telegram` with `TRIGGER=Contradiction`.
4. If no conflict is found, continue silently.

Examples of conflicts:

- АЮ asks for feature X but `ROADMAP.md` marks it deprecated by prior decision.
- A new task contradicts an architectural choice from a prior research memo.
- The same task is assigned to two different roles.
