import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_URL_RE = re.compile(r"https?://[^\s<>\]\)]+|(?:youtu\.be|youtube\.com)/[^\s<>\]\)]+", re.IGNORECASE)
_TELEGRAM_INTERNAL_URL_RE = re.compile(
    r"(?i)^https?://t\.me/(?:c/\d+/\d+|[A-Za-z0-9_]+/\d+)\b"
)
_TRAILING_URL_PUNCTUATION = ".,;:!?)]}\"'"


def source_intake_dir(hermes_home: Path) -> Path:
    return Path(hermes_home) / "source_intake"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _platform_value(platform: Any) -> str:
    return str(getattr(platform, "value", platform) or "")


def _clean_url(raw_url: str) -> str:
    url = str(raw_url or "").strip().rstrip(_TRAILING_URL_PUNCTUATION)
    if url.lower().startswith(("youtu.be/", "youtube.com/")):
        return f"https://{url}"
    return url


def _extract_external_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in _URL_RE.finditer(text or ""):
        url = _clean_url(match.group(0))
        if not url or _TELEGRAM_INTERNAL_URL_RE.search(url):
            continue
        if url in seen:
            continue
        seen.add(url)
        urls.append(url)
    return urls


def _source_kind(url_or_ref: str) -> str:
    if re.search(r"(youtu\.be|youtube\.com)", url_or_ref or "", re.IGNORECASE):
        return "video"
    return "link"


def _source_id(event: Any, url_or_ref: str, *, source_message_id: str) -> str:
    source = getattr(event, "source", None)
    platform = _platform_value(getattr(source, "platform", ""))
    parts = [
        platform,
        str(getattr(source, "chat_id", "") or ""),
        str(getattr(source, "thread_id", "") or ""),
        source_message_id,
        url_or_ref,
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"src_{digest}"


def _base_record(
    event: Any,
    url_or_ref: str,
    *,
    created_at: str,
    source_message_id: str,
    trigger_message_id: str,
) -> dict[str, Any]:
    source = getattr(event, "source", None)
    platform = _platform_value(getattr(source, "platform", ""))
    return {
        "source_id": _source_id(event, url_or_ref, source_message_id=source_message_id),
        "kind": _source_kind(url_or_ref),
        "url_or_ref": url_or_ref,
        "origin_platform": platform,
        "chat_id": str(getattr(source, "chat_id", "") or ""),
        "thread_id": str(getattr(source, "thread_id", "") or ""),
        "message_id": source_message_id,
        "trigger_message_id": trigger_message_id,
        "submitted_by": str(getattr(source, "user_id", "") or ""),
        "created_at": created_at,
        "done": False,
    }


def _append_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True))
            handle.write("\n")


def _existing_source_ids(path: Path, *, event_name: str = "source_discovered") -> set[str]:
    if not path.exists():
        return set()
    existing: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        source_id = str(row.get("source_id") or "")
        if source_id and row.get("event") == event_name:
            existing.add(source_id)
    return existing


def _source_urls_and_message_ids(event: Any) -> tuple[list[str], str, str]:
    trigger_message_id = str(getattr(event, "message_id", "") or "")
    reply_to_text = str(getattr(event, "reply_to_text", "") or "")
    reply_urls = _extract_external_urls(reply_to_text)
    if reply_urls:
        source_message_id = str(getattr(event, "reply_to_message_id", "") or trigger_message_id)
        return reply_urls, source_message_id, trigger_message_id
    return _extract_external_urls(getattr(event, "text", "") or ""), trigger_message_id, trigger_message_id


def record_link_summary_sources(hermes_home: Path, event: Any) -> list[dict[str, Any]]:
    urls, source_message_id, trigger_message_id = _source_urls_and_message_ids(event)
    created_at = _now_iso()
    intake_dir = source_intake_dir(hermes_home)
    ledger_path = intake_dir / "source_ledger.jsonl"
    outbox_path = intake_dir / "sheet_outbox.jsonl"
    existing = _existing_source_ids(ledger_path)
    existing_outbox = _existing_source_ids(outbox_path, event_name="sheet_write_required")
    records: list[dict[str, Any]] = []
    new_records: list[dict[str, Any]] = []
    new_outbox_records: list[dict[str, Any]] = []
    for url in urls:
        record = {
            **_base_record(
                event,
                url,
                created_at=created_at,
                source_message_id=source_message_id,
                trigger_message_id=trigger_message_id,
            ),
            "event": "source_discovered",
            "status": "queued",
            "sheet_status": "pending",
        }
        records.append(record)
        if record["source_id"] not in existing:
            new_records.append(record)
        if record["source_id"] not in existing_outbox:
            new_outbox_records.append(record)

    setattr(event, "telegram_source_ledger_records", records)
    setattr(event, "telegram_source_ledger_ids", [record["source_id"] for record in records])

    _append_jsonl(ledger_path, new_records)
    _append_jsonl(
        outbox_path,
        [
            {
                "event": "sheet_write_required",
                "status": "pending",
                "source_id": record["source_id"],
                "url_or_ref": record["url_or_ref"],
                "created_at": created_at,
            }
            for record in new_outbox_records
        ],
    )
    return records


def record_link_summary_result(
    hermes_home: Path,
    event: Any,
    *,
    response_text: str,
    sheet_write_attempted: bool,
) -> None:
    records = getattr(event, "telegram_source_ledger_records", None)
    if not records:
        records = record_link_summary_sources(hermes_home, event)
    if not records:
        return None

    created_at = _now_iso()
    response_present = bool(str(response_text or "").strip())
    status = "summary_created" if sheet_write_attempted else "published_without_save"
    if not response_present:
        status = "processing"
    sheet_status = "write_attempted" if sheet_write_attempted else "pending"
    event_name = "summary_created" if response_present else "processing"

    intake_dir = source_intake_dir(hermes_home)
    _append_jsonl(
        intake_dir / "source_ledger.jsonl",
        [
            {
                **record,
                "event": event_name,
                "status": status,
                "sheet_status": sheet_status,
                "created_at": created_at,
                "done": False,
            }
            for record in records
        ],
    )
    _append_jsonl(
        intake_dir / "sheet_outbox.jsonl",
        [
            {
                "event": "sheet_write_attempted" if sheet_write_attempted else "sheet_write_missing",
                "status": "attempted" if sheet_write_attempted else "pending",
                "source_id": record["source_id"],
                "url_or_ref": record["url_or_ref"],
                "created_at": created_at,
            }
            for record in records
        ],
    )
    return None
