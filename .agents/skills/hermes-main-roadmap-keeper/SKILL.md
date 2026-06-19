---
name: hermes-main-roadmap-keeper
description: 'The only skill allowed to edit ROADMAP.md. Updates plan, status, in-progress steps, completed items, open questions, and blockers. Use after every state change: task created, assigned, step completed, PR merged, or escalation raised.'
---

Supported operations:

- `add-queued <task>`: add a task to Queued.
- `move-to-progress <task> <owner> <branch>`: move a task to In Progress.
- `update-step <task> <step N/M>`: update step counter.
- `mark-done <task> <PR#>`: move a task to Done.
- `add-open-question <question> <role> <link>`: add an Open Questions entry.
- `add-blocker <description> <blocking-what>`: add an Active Blockers entry.
- `clear-resolved`: remove answered questions and resolved blockers.

On every write:

1. Read current `ROADMAP.md`.
2. Apply the requested operation.
3. Update Last updated timestamp.
4. Write back.
5. Commit with message `chore(roadmap): <op summary>`.

Once Phase 3 hooks are installed, direct edits to `ROADMAP.md` by any other skill or workflow are blocked.
