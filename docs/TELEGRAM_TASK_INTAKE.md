# Telegram Task Intake MVP

Telegram task intake records lightweight tasks from enabled Telegram chats when
a message contains `#задача`, `#task`, `#todo`, or `#дело`.

This is separate from source/link intake. A task marker creates a task record
and does not require the LLM to interpret the message.

## Syntax

Examples:

```text
#задача @ivan #разработка #срочно до:2026-07-01 Проверить лендинг
#task @masha #content due:2026-07-01 Draft post
#todo #sales Call lead
```

Rules:

- task marker is required;
- assignee is `@name` or `assignee:@name`;
- all non-marker hashtags become tags;
- the first non-marker hashtag becomes `category`;
- `#срочно` / `#urgent` maps to `urgent`;
- `#важно` / `#high` maps to `high`;
- due date is explicit only: `due:YYYY-MM-DD`, `deadline:YYYY-MM-DD`, or `до:YYYY-MM-DD`;
- missing assignee is stored as `assignee_status=needs_assignee`.

Reply metadata is preserved when available:

- trigger message id;
- replied-to message id;
- replied-to text.

## Local Durable Files

Under `HERMES_HOME`:

```text
task_intake/task_ledger.jsonl
task_intake/sheet_outbox.jsonl
task_intake/destination_outbox.jsonl
```

The local ledger is written before any Google Sheet write. If Google auth,
MCP, or the Sheet is unavailable, the task remains pending in
`sheet_outbox.jsonl`.

## Google Sheet Buffer

Task Sheet columns:

```text
created_at, updated_at, task_id, status, project, category, tags, priority,
due_at, assignee, assignee_status, requester, chat_id, thread_id, message_id,
reply_to_message_id, message_link, raw_text, task_text, destination,
external_id, sheet_status, sync_status, last_error_safe
```

## Environment

```text
TELEGRAM_TASK_INTAKE_ENABLED=true
TELEGRAM_TASK_INTAKE_CHATS=-100111,-100222
TELEGRAM_TASK_MARKERS=задача,task,todo,дело
TELEGRAM_TASK_DEFAULT_STATUS=new
TELEGRAM_TASK_SHEET_ID=<spreadsheet id>
TELEGRAM_TASK_SHEET_TAB=Tasks
```

Optional:

```text
TELEGRAM_TASK_SHEET_RANGE=Tasks!A:X
TELEGRAM_TASK_SHEET_REPLAY_STARTUP_LIMIT=3
TELEGRAM_TASK_SHEET_REPLAY_SWEEP_INTERVAL_SECONDS=900
```

Google write path:

1. Use existing Google Workspace MCP token with spreadsheet scope when present.
2. Otherwise use the existing `google_api.py` path.
3. If neither works, keep the task pending and return only a safe public ack.

## Public Acks

Success:

```text
Записал задачу: @ivan / разработка / new.
```

Sheet unavailable:

```text
Записал задачу, таблица временно недоступна, поставил в очередь.
```

Missing assignee:

```text
Не понял исполнителя, записал задачу без исполнителя.
```

Technical Google/MCP errors are not sent to group chats.

## MAIN/QA Verification

No production deploy is included in the PR. To verify after merge/deploy:

1. Enable the feature flags in the approved production configuration path.
2. Restart Hermes only through the MAIN production process.
3. Post a task marker in an enabled Telegram chat.
4. Confirm a row appears in the configured `Tasks` tab.
5. Temporarily disable Sheet auth in a safe test environment and confirm the
   public ack says the task was queued.
6. Confirm `task_intake/sheet_outbox.jsonl` keeps the pending task.
7. Restore Sheet auth and confirm replay marks it succeeded.
