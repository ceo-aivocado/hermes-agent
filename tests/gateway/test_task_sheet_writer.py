from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource
from gateway.task_intake import TaskIntakeRules, parse_task_intake
from gateway.task_sheet_writer import (
    TASK_SHEET_COLUMNS,
    build_task_sheet_row,
    task_sheet_safe_error_class,
)


def _record():
    event = MessageEvent(
        text="#задача @ivan #разработка #важно due:2026-07-01 Проверить лендинг",
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="-100",
            chat_type="group",
            thread_id="7",
            user_id="10954083",
            user_name="АЮ",
        ),
        message_id="42",
    )
    record = parse_task_intake(event, rules=TaskIntakeRules())
    assert record is not None
    return record


def test_record_maps_to_exact_sheet_columns():
    record = _record()

    row = build_task_sheet_row(record)

    assert TASK_SHEET_COLUMNS == (
        "created_at",
        "updated_at",
        "task_id",
        "status",
        "project",
        "category",
        "tags",
        "priority",
        "due_at",
        "assignee",
        "assignee_status",
        "requester",
        "chat_id",
        "thread_id",
        "message_id",
        "reply_to_message_id",
        "message_link",
        "raw_text",
        "task_text",
        "destination",
        "external_id",
        "sheet_status",
        "sync_status",
        "last_error_safe",
    )
    assert row[TASK_SHEET_COLUMNS.index("task_id")] == record.task_id
    assert row[TASK_SHEET_COLUMNS.index("assignee")] == "@ivan"
    assert row[TASK_SHEET_COLUMNS.index("tags")] == "разработка,важно"
    assert row[TASK_SHEET_COLUMNS.index("priority")] == "high"
    assert row[TASK_SHEET_COLUMNS.index("task_text")] == "Проверить лендинг"


def test_sheet_errors_are_public_safe_classes():
    assert task_sheet_safe_error_class("google_api.py not authenticated") == "google_sheet_auth_failed"
    assert task_sheet_safe_error_class("timed out while connecting") == "google_sheet_unavailable"
    assert task_sheet_safe_error_class("spreadsheet not found") == "google_sheet_not_found"
    assert task_sheet_safe_error_class("some raw stack trace") == "google_sheet_write_failed"
