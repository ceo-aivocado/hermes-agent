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
        "chat_type": str(getattr(source, "chat_type", "") or ""),
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


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def _existing_source_ids(path: Path, *, event_name: str = "source_discovered") -> set[str]:
    existing: set[str] = set()
    for row in _read_jsonl(path):
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
    sheet_write_succeeded: bool = False,
    sheet_write_failed: bool = False,
) -> None:
    records = getattr(event, "telegram_source_ledger_records", None)
    if not records:
        records = record_link_summary_sources(hermes_home, event)
    if not records:
        return None

    created_at = _now_iso()
    response_present = bool(str(response_text or "").strip())
    status = "summary_created" if sheet_write_attempted else "published_without_save"
    if sheet_write_failed:
        status = "published_without_save"
    if not response_present:
        status = "processing"
    if sheet_write_succeeded:
        sheet_status = "succeeded"
    elif sheet_write_failed:
        sheet_status = "failed"
    else:
        sheet_status = "write_attempted" if sheet_write_attempted else "pending"
    event_name = "summary_created" if response_present else "processing"

    if sheet_write_succeeded:
        outbox_event = "sheet_write_succeeded"
        outbox_status = "succeeded"
    elif sheet_write_failed:
        outbox_event = "sheet_write_failed"
        outbox_status = "pending"
    else:
        outbox_event = "sheet_write_attempted" if sheet_write_attempted else "sheet_write_missing"
        outbox_status = "attempted" if sheet_write_attempted else "pending"

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
                "done": bool(response_present and sheet_write_succeeded),
            }
            for record in records
        ],
    )
    _append_jsonl(
        intake_dir / "sheet_outbox.jsonl",
        [
            {
                "event": outbox_event,
                "status": outbox_status,
                "source_id": record["source_id"],
                "url_or_ref": record["url_or_ref"],
                "created_at": created_at,
            }
            for record in records
        ],
    )
    return None


def recover_source_intake_pending(hermes_home: Path) -> dict[str, int]:
    """Repair and mark unfinished source intake rows after gateway restart."""
    intake_dir = source_intake_dir(hermes_home)
    ledger_path = intake_dir / "source_ledger.jsonl"
    outbox_path = intake_dir / "sheet_outbox.jsonl"
    ledger_rows = _read_jsonl(ledger_path)
    outbox_rows = _read_jsonl(outbox_path)

    discovered_by_id: dict[str, dict[str, Any]] = {}
    latest_source_row_by_id: dict[str, dict[str, Any]] = {}
    recovery_keys: set[tuple[str, str]] = set()
    for row in ledger_rows:
        source_id = str(row.get("source_id") or "")
        if not source_id:
            continue
        event_name = row.get("event")
        if event_name == "source_discovered" and source_id not in discovered_by_id:
            discovered_by_id[source_id] = row
        if event_name != "recovery_required":
            latest_source_row_by_id[source_id] = row
        else:
            reason = str(row.get("recovery_reason") or "")
            if reason:
                recovery_keys.add((source_id, reason))

    outbox_events_by_id: dict[str, set[str]] = {}
    pending_outbox_ids: set[str] = set()
    attempted_outbox_ids: set[str] = set()
    for row in outbox_rows:
        source_id = str(row.get("source_id") or "")
        if not source_id:
            continue
        event_name = str(row.get("event") or "")
        outbox_events_by_id.setdefault(source_id, set()).add(event_name)
        if row.get("status") == "pending":
            pending_outbox_ids.add(source_id)
        if row.get("status") == "attempted" or event_name == "sheet_write_attempted":
            attempted_outbox_ids.add(source_id)

    created_at = _now_iso()
    repaired_outbox_rows: list[dict[str, Any]] = []
    recovery_rows: list[dict[str, Any]] = []
    for source_id, discovered in discovered_by_id.items():
        if "sheet_write_required" not in outbox_events_by_id.get(source_id, set()):
            repaired_outbox_rows.append(
                {
                    "event": "sheet_write_required",
                    "status": "pending",
                    "source_id": source_id,
                    "url_or_ref": discovered.get("url_or_ref", ""),
                    "created_at": created_at,
                }
            )
            pending_outbox_ids.add(source_id)

        latest = latest_source_row_by_id.get(source_id) or discovered
        latest_event = latest.get("event")
        sheet_status = latest.get("sheet_status")
        reason = ""
        if source_id not in attempted_outbox_ids:
            if latest_event in {"source_discovered", "processing"}:
                reason = "source_processing_incomplete"
            elif sheet_status == "pending" or source_id in pending_outbox_ids:
                reason = "sheet_write_pending"
        if not reason or (source_id, reason) in recovery_keys:
            continue
        recovery_rows.append(
            {
                **discovered,
                "event": "recovery_required",
                "status": "recovery_pending",
                "sheet_status": "pending",
                "created_at": created_at,
                "done": False,
                "recovery_reason": reason,
            }
        )
        recovery_keys.add((source_id, reason))

    _append_jsonl(outbox_path, repaired_outbox_rows)
    _append_jsonl(ledger_path, recovery_rows)
    return {
        "sources_seen": len(discovered_by_id),
        "repaired_outbox": len(repaired_outbox_rows),
        "recovery_required": len(recovery_rows),
    }


def pending_source_replay_records(
    hermes_home: Path,
    *,
    limit: int = 25,
    max_attempts: int = 3,
) -> list[dict[str, Any]]:
    intake_dir = source_intake_dir(hermes_home)
    ledger_rows = _read_jsonl(intake_dir / "source_ledger.jsonl")
    outbox_rows = _read_jsonl(intake_dir / "sheet_outbox.jsonl")

    discovered_by_id: dict[str, dict[str, Any]] = {}
    latest_source_row_by_id: dict[str, dict[str, Any]] = {}
    recovery_required_ids: set[str] = set()
    replay_attempts_by_id: dict[str, int] = {}
    for row in ledger_rows:
        source_id = str(row.get("source_id") or "")
        if not source_id:
            continue
        event_name = str(row.get("event") or "")
        if event_name == "source_discovered" and source_id not in discovered_by_id:
            discovered_by_id[source_id] = row
        if event_name == "recovery_required":
            recovery_required_ids.add(source_id)
            continue
        if event_name.startswith("source_replay_"):
            replay_attempts_by_id[source_id] = replay_attempts_by_id.get(source_id, 0) + (
                1 if event_name == "source_replay_started" else 0
            )
        latest_source_row_by_id[source_id] = row

    sheet_attempted_ids: set[str] = set()
    sheet_succeeded_ids: set[str] = set()
    sheet_pending_ids: set[str] = set()
    for row in outbox_rows:
        source_id = str(row.get("source_id") or "")
        if not source_id:
            continue
        event_name = str(row.get("event") or "")
        if row.get("status") == "succeeded" or event_name == "sheet_write_succeeded":
            sheet_succeeded_ids.add(source_id)
        if row.get("status") == "attempted" or event_name == "sheet_write_attempted":
            sheet_attempted_ids.add(source_id)
        if row.get("status") == "pending":
            sheet_pending_ids.add(source_id)

    pending: list[dict[str, Any]] = []
    for source_id, discovered in discovered_by_id.items():
        if source_id in sheet_succeeded_ids:
            continue
        if source_id in sheet_attempted_ids:
            continue
        latest = latest_source_row_by_id.get(source_id) or discovered
        needs_replay = (
            source_id in recovery_required_ids
            or source_id in sheet_pending_ids
            or latest.get("sheet_status") == "pending"
        )
        if not needs_replay:
            continue
        attempts = replay_attempts_by_id.get(source_id, 0)
        if attempts >= max(0, max_attempts):
            continue
        record = dict(discovered)
        record["replay_attempts"] = attempts
        pending.append(record)
        if len(pending) >= limit:
            break
    return pending


def record_source_replay_started(hermes_home: Path, source_record: dict[str, Any]) -> None:
    created_at = _now_iso()
    _append_jsonl(
        source_intake_dir(hermes_home) / "source_ledger.jsonl",
        [
            {
                **source_record,
                "event": "source_replay_started",
                "status": "replay_processing",
                "sheet_status": "pending",
                "created_at": created_at,
                "done": False,
            }
        ],
    )


def record_source_replay_result(
    hermes_home: Path,
    source_record: dict[str, Any],
    *,
    response_text: str = "",
    sheet_write_attempted: bool = False,
    sheet_write_succeeded: bool = False,
    sheet_write_failed: bool = False,
    error: str = "",
) -> None:
    created_at = _now_iso()
    replay_failed = bool(error or sheet_write_failed)
    event_name = "source_replay_failed" if replay_failed else "source_replay_completed"
    status = (
        "replay_failed"
        if replay_failed
        else "replay_completed"
        if sheet_write_succeeded
        else "replay_pending"
    )
    if sheet_write_succeeded:
        sheet_status = "succeeded"
    elif sheet_write_failed:
        sheet_status = "failed"
    else:
        sheet_status = "write_attempted" if sheet_write_attempted else "pending"
    _append_jsonl(
        source_intake_dir(hermes_home) / "source_ledger.jsonl",
        [
            {
                **source_record,
                "event": event_name,
                "status": status,
                "sheet_status": sheet_status,
                "created_at": created_at,
                "done": bool(sheet_write_succeeded),
                "response_present": bool(str(response_text or "").strip()),
                "error": str(error or "")[:500],
            }
        ],
    )
