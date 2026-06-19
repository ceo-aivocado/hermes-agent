---
name: hermes-dev-implement
description: 'Implement a feature from a PM spec. Use when Developer Core or Developer Edge receives a lane:dev-core or lane:dev-edge handoff.'
---

Pre-flight:

1. Confirm domain matches assignment. Core may edit only `src/hermes_agent/core/`, `src/hermes_agent/runtime/`, `src/hermes_agent/gateway/`, and `src/hermes_agent/orchestration/`. Edge may edit only `src/hermes_agent/integrations/`, `src/hermes_agent/plugins/`, `src/hermes_agent/automations/`, and `src/hermes_agent/telegram/`.
2. If the spec requires cross-domain work, escalate per Architectural Decision.
3. Confirm worktree mode is on.
4. Create feature branch `feature/core-<slug>` or `feature/edge-<slug>`.
5. Update `ROADMAP.md`: move task to In Progress.

Implementation loop per acceptance criterion:

1. Write test first.
2. Implement minimal code.
3. Refactor if needed while keeping tests green.
4. Update `ROADMAP.md` step counter.
5. On failure, retry up to three times. If still failing, escalate Stuck-after-retry.

Pre-PR:

- All acceptance criteria are green.
- Relevant tests pass.
- No edits outside assigned domain.
- `ROADMAP.md` step is final.

Open a PR with description referencing the spec issue. Tag MAIN for review.

Do not ask intermediate confirmations. Continue until done or until a real escalation trigger fires.
