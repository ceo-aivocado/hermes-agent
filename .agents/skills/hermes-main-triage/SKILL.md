---
name: hermes-main-triage
description: 'Intake a free-form task from АЮ, classify lane/type/risk/domain, assign the correct Hermes Bot role, and add it to ROADMAP. Use when АЮ says "новая задача", "вот идея", "сделай X", or hands over a batch of tasks at the start of a session.'
---

For each task in input:

1. Classify lane: pm for vague ideas, research for find/compare questions, dev-core or dev-edge for code changes in a known domain, qa for bug reports.
2. Classify type, `status:triage`, risk, and domain labels.
3. Open a GitHub issue with labels via `gh issue create`.
4. Add the task to `ROADMAP.md` Queued via `hermes-main-roadmap-keeper`.
5. If owner is clear, assign and trigger handoff; move it to In Progress.
6. If multiple tasks are provided, process all without asking confirmation between them.
7. Return summary: N tasks classified, M routed to role, K queued.

Do not ask АЮ for clarification per task. Use the best inference from context. Escalate only on the five Execution Policy triggers in `AGENTS.md`.
