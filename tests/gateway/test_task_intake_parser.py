from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource
from gateway.task_intake import TaskIntakeRules, parse_task_intake


def _event(
    text: str,
    *,
    chat_id: str = "-100",
    thread_id: str | None = "7",
    message_id: str = "42",
    user_id: str = "10954083",
    user_name: str = "АЮ",
    reply_to_text: str | None = None,
    reply_to_message_id: str | None = None,
) -> MessageEvent:
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id=chat_id,
            chat_type="group",
            thread_id=thread_id,
            user_id=user_id,
            user_name=user_name,
        ),
        message_id=message_id,
        reply_to_text=reply_to_text,
        reply_to_message_id=reply_to_message_id,
    )


def test_parse_russian_task_marker_with_assignee_tags_priority_and_due_date():
    record = parse_task_intake(
        _event("#задача @ivan #разработка #срочно до:2026-07-01 Проверить лендинг"),
        rules=TaskIntakeRules(),
    )

    assert record is not None
    assert record.task_id == "task_268c534411007d76"
    assert record.status == "new"
    assert record.assignee == "@ivan"
    assert record.assignee_status == "assigned"
    assert record.tags == ["разработка", "срочно"]
    assert record.category == "разработка"
    assert record.priority == "urgent"
    assert record.due_at == "2026-07-01"
    assert record.task_text == "Проверить лендинг"
    assert record.requester == "10954083"
    assert record.chat_id == "-100"
    assert record.thread_id == "7"
    assert record.message_id == "42"


def test_parse_english_task_marker_deduplicates_hashtags_and_preserves_raw_text():
    record = parse_task_intake(
        _event("#task @masha #content #content due:2026-07-01 Draft post"),
        rules=TaskIntakeRules(),
    )

    assert record is not None
    assert record.tags == ["content"]
    assert record.category == "content"
    assert record.due_at == "2026-07-01"
    assert record.task_text == "Draft post"
    assert record.raw_text == "#task @masha #content #content due:2026-07-01 Draft post"


def test_missing_assignee_is_recorded_as_needs_assignee():
    record = parse_task_intake(_event("#todo #sales Call lead"), rules=TaskIntakeRules())

    assert record is not None
    assert record.assignee == ""
    assert record.assignee_status == "needs_assignee"
    assert record.category == "sales"
    assert record.priority == "normal"
    assert record.task_text == "Call lead"


def test_no_marker_returns_none():
    assert parse_task_intake(_event("just context"), rules=TaskIntakeRules()) is None


def test_reply_metadata_is_preserved():
    record = parse_task_intake(
        _event(
            "#задача @ivan разобрать это",
            reply_to_text="Исходный контекст задачи",
            reply_to_message_id="41",
        ),
        rules=TaskIntakeRules(),
    )

    assert record is not None
    assert record.reply_to_message_id == "41"
    assert record.reply_to_text == "Исходный контекст задачи"
