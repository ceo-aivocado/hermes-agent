---
name: hermes-qa-fix
description: 'Fix a triaged bug. Use when QA picks up an issue with lane:qa and status:in_progress.'
---

Follow the same loop as `hermes-dev-implement`, with these differences:

- Scope is only the reported bug. No scope creep.
- Always add a regression test that fails on the bug before the fix.
- Branch name is `fix/<issue-number>-<slug>`.
- If the fix requires touching outside QA's scope, such as a refactor, escalate Architectural Decision instead of silently expanding.

QA has implicit cross-domain access for bug fixes only. Justify in the PR description why the fix had to land where it did.
