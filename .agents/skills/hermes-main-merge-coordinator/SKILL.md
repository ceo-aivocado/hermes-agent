---
name: hermes-main-merge-coordinator
description: 'Decide merge order when two or more PRs are ready, avoiding conflicts and dependency mistakes. Use when MAIN reviews any PR and there are other open PRs.'
---

1. List open PRs ready for merge with `gh pr list --state open --json number,title,headRefName,labels`.
2. For each PR, identify touched files.
3. Detect overlaps between PRs. If overlaps exist, merge first the PR with fewer dependents, then rebase the other.
4. Merge in this order: production-risk bug fixes, infrastructure, features, docs.
5. After each merge, trigger `hermes-main-roadmap-keeper` to update status.
6. If rebase causes more than five conflicts on a PR, bounce it back to the author Developer thread.

Never merge two PRs in parallel. Always merge sequentially.
