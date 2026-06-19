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
   🔔 Hermes Bot | <ROLE> | <TRIGGER>
   Контекст: <1-2 lines>
   Нужно решение: <specific question with A/B/C if applicable>
   Что встало: <what blocks>
   Ссылка: <Codex thread URL or GitHub issue URL>
   ```

2. Send it with `scripts/send_escalation.py`:

   ```bash
   .agents/skills/hermes-escalate-telegram/scripts/send_escalation.py \
     --role "<ROLE>" \
     --trigger "<TRIGGER>" \
     --context "<1-2 lines>" \
     --question "<specific question with A/B/C if applicable>" \
     --blocked-by "<what blocks>" \
     --link "<Codex thread URL or GitHub issue URL>"
   ```

   The script POSTs to Telegram Bot API `sendMessage`.
   For local validation without putting the token in shell history, pass
   `--token-stdin` and write the token to stdin.

3. Add entry to `ROADMAP.md` Open Questions via roadmap keeper.
4. Set task status to `status:blocked` with reason `awaiting-owner-decision`.
5. Stop work on this task. Continue on other independent tasks if any.

Environment:

- `AIVOCADO_BOT_TOKEN`: required Telegram bot token secret.
- `OWNER_TELEGRAM_ID`: owner chat id. Defaults to `10954083` if absent.
