---
name: hermes-pm-spec
description: 'Convert a vague feature idea into a Developer-ready specification with definition of done, edge cases, test plan, and target domain. Use when PM receives lane:pm work or АЮ says "продумай фичу" or "сделай спеку для X".'
---

Use this template:

```markdown
## Feature: <name>

## Why
<problem this solves, who benefits>

## User-facing behavior
<what the user sees / does>

## Acceptance criteria
- [ ] criterion 1
- [ ] criterion 2

## Edge cases
- <edge 1>: <expected behavior>

## Out of scope
- <not doing X because Y>

## Domain
core | edge

## Test plan
<unit / integration / smoke>

## Open questions
<must be resolved before handoff to Developer; escalate if needed>
```

After drafting:

1. Run self-review with `hermes-pm-self-review`.
2. If it passes, hand off to Developer Core or Developer Edge based on Domain.
3. If it fails, iterate or escalate ambiguity.

Never hand off an incomplete spec. Bouncing back to АЮ is better than handing Developer something fuzzy.
