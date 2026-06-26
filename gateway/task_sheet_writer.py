from typing import Any

from gateway.task_intake import TaskIntakeRecord


TASK_SHEET_COLUMNS = (
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


def _record_dict(record: TaskIntakeRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(record, TaskIntakeRecord):
        return record.to_dict()
    return dict(record)


def build_task_sheet_row(record: TaskIntakeRecord | dict[str, Any]) -> list[str]:
    payload = _record_dict(record)
    row: list[str] = []
    for column in TASK_SHEET_COLUMNS:
        value = payload.get(column, "")
        if isinstance(value, list):
            value = ",".join(str(item) for item in value)
        row.append(str(value or ""))
    return row


def task_sheet_safe_error_class(error: str) -> str:
    lowered = str(error or "").lower()
    if not lowered:
        return ""
    if "not authenticated" in lowered or "unauthorized" in lowered or "401" in lowered:
        return "google_sheet_auth_failed"
    if "not found" in lowered or "404" in lowered:
        return "google_sheet_not_found"
    if "timeout" in lowered or "timed out" in lowered or "unavailable" in lowered:
        return "google_sheet_unavailable"
    return "google_sheet_write_failed"
