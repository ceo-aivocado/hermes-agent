---
name: ci-failure-triage
description: 'Triage failing CI/GitHub Actions checks for Hermes Bot PRs. Use when a workflow fails or АЮ says "почини CI".'
---

> Imported from: https://github.com/openai/skills (ci-failure-triage)
> Imported on: 2026-06-19
> Local edits: Lightweight Hermes Bot copy because the upstream skill was not vendored in this checkout.

# CI Failure Triage

1. Identify the failing workflow/run with `gh run list` or PR checks.
2. Fetch focused logs with `gh run view --log-failed`.
3. Separate repo-controlled failures from external, secrets, and infrastructure failures.
4. If repo-controlled, fix in the current branch and rerun the smallest relevant local check.
5. If external, report the exact blocker and do not mask the failure.
6. Update the PR with what failed, what changed, and verification.
