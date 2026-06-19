---
name: hermes-pm-self-review
description: 'PM checks its own spec against a quality checklist before handoff. Trigger automatically inside hermes-pm-spec. Use also when АЮ says "проверь спеку".'
---

Checklist:

- [ ] Why is clear, not just what.
- [ ] Acceptance criteria are testable.
- [ ] At least two edge cases are listed.
- [ ] Out of scope is explicit.
- [ ] Domain is assigned as core or edge, never both.
- [ ] Test plan is named.
- [ ] Open questions are empty or escalated.

Return `PASS` or `FAIL <reason>`. On FAIL, PM iterates and does not hand off.
