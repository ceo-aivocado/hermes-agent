---
name: hermes-qa-bug-intake
description: 'Convert a bug report with screenshot and description from АЮ into a structured GitHub issue with reproduction steps. Use when АЮ says "баг", "не работает", "сломалось", or attaches a screenshot via Telegram.'
---

1. Read screenshot with OCR if needed and read the description.
2. Extract expected behavior, actual behavior, timestamp, and environment.
3. If reproduction steps are unclear, ask one clarifying question via `hermes-escalate-telegram` using the Ambiguity trigger.
4. Open an issue with this template:

   ```markdown
   ## Expected
   ## Actual
   ## Reproduction steps
   ## Environment
   ## Screenshot
   ```

5. Apply labels: `lane:qa`, `type:bug`, `status:triage`, and domain labels.
6. Update `ROADMAP.md` via roadmap keeper.
7. If severity is high, such as production breakage or data loss, also notify MAIN via comment.
