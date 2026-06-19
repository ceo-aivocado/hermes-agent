---
name: hermes-research-memo
description: 'Conduct external research and produce a structured decision memo. Use when АЮ says "исследуй", "найди", "сравни", "что лучше", or when MAIN assigns lane:research work.'
---

Use this template:

```markdown
## Research: <topic>

## Question
<one-liner: what decision this enables>

## Options considered
- A: <name> - <pros, cons, cost, refs>
- B: ...

## Recommendation
<one option, with rationale in 2-3 sentences>

## Trade-offs
<what we give up>

## Sources
[1] <title> - <URL>
[2] ...

## Next step
<PM creates spec / MAIN decides / Developer experiments>
```

Method:

1. Define the question precisely; escalate if it is too vague to answer.
2. Search three to five sources: web, official docs, and GitHub as appropriate.
3. Compare options using consistent criteria.
4. Recommend one option. Do not end with "it depends" without a follow-up question.
5. Hand off to PM if feature-related, or MAIN if infra/architecture-related.
