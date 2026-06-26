import hashlib
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any


_HASHTAG_RE = re.compile(r"(?<!\w)#([A-Za-z0-9_А-Яа-яЁё-]+)", re.UNICODE)
_ASSIGNEE_RE = re.compile(
    r"(?:(?<!\w)assignee:\s*)?(@[A-Za-z0-9_А-Яа-яЁё.-]+)",
    re.IGNORECASE | re.UNICODE,
)
_DUE_RE = re.compile(r"(?<!\w)(?:due|deadline|до):\s*(\d{4}-\d{2}-\d{2})\b", re.IGNORECASE)


@dataclass(frozen=True)
class TaskIntakeRules:
    markers: tuple[str, ...] = ("задача", "task", "todo", "дело")
    default_status: str = "new"
    default_destination: str = "google_sheet"
    urgent_tags: tuple[str, ...] = ("срочно", "urgent")
    high_tags: tuple[str, ...] = ("важно", "high")


@dataclass(frozen=True)
class TaskIntakeRecord:
    created_at: str
    updated_at: str
    task_id: str
    status: str
    project: str
    category: str
    tags: list[str] = field(default_factory=list)
    priority: str = "normal"
    due_at: str = ""
    assignee: str = ""
    assignee_status: str = "needs_assignee"
    requester: str = ""
    chat_id: str = ""
    thread_id: str = ""
    message_id: str = ""
    reply_to_message_id: str = ""
    reply_to_text: str = ""
    message_link: str = ""
    raw_text: str = ""
    task_text: str = ""
    destination: str = "google_sheet"
    external_id: str = ""
    sheet_status: str = "pending"
    sync_status: str = "pending"
    last_error_safe: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _platform_value(platform: Any) -> str:
    return str(getattr(platform, "value", platform) or "")


def _normalize_token(value: str) -> str:
    return str(value or "").strip().lower().lstrip("#")


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _task_id(event: Any, *, marker_index: int) -> str:
    source = getattr(event, "source", None)
    parts = [
        _platform_value(getattr(source, "platform", "")),
        str(getattr(source, "chat_id", "") or ""),
        str(getattr(source, "thread_id", "") or ""),
        str(getattr(event, "message_id", "") or getattr(source, "message_id", "") or ""),
        str(marker_index),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"task_{digest}"


def _task_text(raw_text: str) -> str:
    text = _HASHTAG_RE.sub(" ", raw_text or "")
    text = _ASSIGNEE_RE.sub(" ", text)
    text = _DUE_RE.sub(" ", text)
    return " ".join(text.split())


def parse_task_intake(event: Any, *, rules: TaskIntakeRules) -> TaskIntakeRecord | None:
    raw_text = str(getattr(event, "text", "") or "").strip()
    if not raw_text:
        return None

    marker_tokens = {_normalize_token(marker) for marker in rules.markers}
    hashtag_matches = list(_HASHTAG_RE.finditer(raw_text))
    marker_index = -1
    marker_count = 0
    tags: list[str] = []
    for match in hashtag_matches:
        token = match.group(1)
        normalized = _normalize_token(token)
        if normalized in marker_tokens:
            if marker_index < 0:
                marker_index = marker_count
            marker_count += 1
            continue
        tags.append(token)

    if marker_index < 0:
        return None

    tags = _dedupe_preserve_order(tags)
    assignee_match = _ASSIGNEE_RE.search(raw_text)
    assignee = assignee_match.group(1) if assignee_match else ""
    assignee_status = "assigned" if assignee else "needs_assignee"
    due_match = _DUE_RE.search(raw_text)
    due_at = due_match.group(1) if due_match else ""

    normalized_tags = {_normalize_token(tag) for tag in tags}
    urgent = {_normalize_token(tag) for tag in rules.urgent_tags}
    high = {_normalize_token(tag) for tag in rules.high_tags}
    if normalized_tags & urgent:
        priority = "urgent"
    elif normalized_tags & high:
        priority = "high"
    else:
        priority = "normal"

    source = getattr(event, "source", None)
    created_at = _now_iso()
    return TaskIntakeRecord(
        created_at=created_at,
        updated_at=created_at,
        task_id=_task_id(event, marker_index=marker_index),
        status=rules.default_status,
        project="",
        category=tags[0] if tags else "",
        tags=tags,
        priority=priority,
        due_at=due_at,
        assignee=assignee,
        assignee_status=assignee_status,
        requester=str(getattr(source, "user_id", "") or ""),
        chat_id=str(getattr(source, "chat_id", "") or ""),
        thread_id=str(getattr(source, "thread_id", "") or ""),
        message_id=str(getattr(event, "message_id", "") or getattr(source, "message_id", "") or ""),
        reply_to_message_id=str(getattr(event, "reply_to_message_id", "") or ""),
        reply_to_text=str(getattr(event, "reply_to_text", "") or ""),
        message_link=str(getattr(event, "message_link", "") or ""),
        raw_text=raw_text,
        task_text=_task_text(raw_text),
        destination=rules.default_destination,
    )
