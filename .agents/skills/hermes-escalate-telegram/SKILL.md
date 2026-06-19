---
name: hermes-escalate-telegram
description: 'Send an escalation push to АЮ''s Telegram. Use only when one of the five Execution Policy escalation triggers is met. Never use for routine progress reports.'
---

Pre-check, block if any answer is false:

- Is this one of the five triggers: Contradiction, Architectural decision, Irreversible action, Stuck-after-retry, or Ambiguity?
- For errors, have three attempts failed?
- Have `AGENTS.md`, `ROADMAP.md`, docs, and existing code been checked for the answer?

If pre-check passes:

1. Compose payload:

   ```text
   Hermes Bot | <ROLE> | <TRIGGER>
   Контекст: <1-2 lines>
   Нужно решение: <specific question with A/B/C if applicable>
   Что встало: <what blocks>
   Ссылка: <Codex thread URL or GitHub issue URL>
   ```

2. POST to Telegram Bot API:
   - URL: `https://api.telegram.org/bot$BOT_TOKEN/sendMessage`
   - body: `chat_id=10954083&text=<payload>&parse_mode=Markdown`
3. Add entry to `ROADMAP.md` Open Questions via roadmap keeper.
4. Set task status to `status:blocked` with reason `awaiting-owner-decision`.
5. Stop work on this task. Continue on other independent tasks if any.

Bot token comes from secret `HERMES_ESCALATION_BOT_TOKEN`.
