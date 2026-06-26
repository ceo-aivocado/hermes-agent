import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from gateway.task_intake import TaskIntakeRecord
from gateway.task_sheet_writer import task_sheet_safe_error_class


def task_intake_dir(hermes_home: Path) -> Path:
    return Path(hermes_home) / "task_intake"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _existing_task_ids(path: Path, *, event_name: str = "task_detected") -> set[str]:
    return {
        str(row.get("task_id") or "")
        for row in _read_jsonl(path)
        if row.get("event") == event_name and row.get("task_id")
    }


def _outbox_finished_task_ids(path: Path) -> set[str]:
    finished: set[str] = set()
    for row in _read_jsonl(path):
        if row.get("event") == "sheet_write_succeeded" and row.get("task_id"):
            finished.add(str(row["task_id"]))
    return finished


def _record_payload(record: TaskIntakeRecord | dict[str, Any]) -> dict[str, Any]:
    if isinstance(record, TaskIntakeRecord):
        return record.to_dict()
    return dict(record)


def record_task_intake(hermes_home: Path, record: TaskIntakeRecord) -> dict[str, int]:
    intake_dir = task_intake_dir(hermes_home)
    ledger_path = intake_dir / "task_ledger.jsonl"
    outbox_path = intake_dir / "sheet_outbox.jsonl"
    destination_path = intake_dir / "destination_outbox.jsonl"
    existing_tasks = _existing_task_ids(ledger_path)
    existing_outbox = _existing_task_ids(outbox_path, event_name="sheet_write_required")
    payload = record.to_dict()
    now = _now_iso()

    if record.task_id in existing_tasks:
        _append_jsonl(
            ledger_path,
            [
                {
                    **payload,
                    "event": "task_duplicate",
                    "status": record.status,
                    "created_at": now,
                }
            ],
        )
        return {"recorded": 0, "duplicates": 1, "sheet_queued": 0, "destination_queued": 0}

    _append_jsonl(
        ledger_path,
        [
            {
                **payload,
                "event": "task_detected",
                "status": record.status,
                "sheet_status": "pending",
                "sync_status": "pending",
            }
        ],
    )
    sheet_rows = []
    if record.task_id not in existing_outbox:
        sheet_rows.append(
            {
                **payload,
                "event": "sheet_write_required",
                "status": "pending",
                "sheet_status": "pending",
            }
        )
    _append_jsonl(outbox_path, sheet_rows)

    destination_rows = []
    if record.destination and record.destination != "google_sheet":
        destination_rows.append(
            {
                **payload,
                "event": "destination_sync_required",
                "status": "pending",
                "sync_status": "pending",
            }
        )
    _append_jsonl(destination_path, destination_rows)
    return {
        "recorded": 1,
        "duplicates": 0,
        "sheet_queued": len(sheet_rows),
        "destination_queued": len(destination_rows),
    }


def pending_task_sheet_outbox_records(hermes_home: Path, *, limit: int | None = None) -> list[dict[str, Any]]:
    outbox_path = task_intake_dir(hermes_home) / "sheet_outbox.jsonl"
    finished = _outbox_finished_task_ids(outbox_path)
    pending: list[dict[str, Any]] = []
    seen: set[str] = set()
    for row in _read_jsonl(outbox_path):
        task_id = str(row.get("task_id") or "")
        if row.get("event") != "sheet_write_required" or not task_id:
            continue
        if task_id in finished or task_id in seen:
            continue
        seen.add(task_id)
        pending.append(row)
        if limit is not None and len(pending) >= limit:
            break
    return pending


def record_task_sheet_append_started(hermes_home: Path, record: TaskIntakeRecord | dict[str, Any]) -> None:
    payload = _record_payload(record)
    _append_jsonl(
        task_intake_dir(hermes_home) / "sheet_outbox.jsonl",
        [
            {
                **payload,
                "event": "sheet_write_started",
                "status": "attempted",
                "updated_at": _now_iso(),
            }
        ],
    )


def record_task_sheet_append_result(
    hermes_home: Path,
    record: TaskIntakeRecord | dict[str, Any],
    *,
    succeeded: bool = False,
    blocked: bool = False,
    error: str = "",
) -> None:
    payload = _record_payload(record)
    now = _now_iso()
    safe_error = "" if succeeded else task_sheet_safe_error_class(error)
    event_name = "sheet_write_succeeded" if succeeded else "sheet_write_failed"
    if blocked:
        event_name = "sheet_write_blocked"
    status = "succeeded" if succeeded else "pending"
    sheet_status = "succeeded" if succeeded else "pending"
    row = {
        **payload,
        "event": event_name,
        "status": status,
        "sheet_status": sheet_status,
        "last_error_safe": safe_error,
        "updated_at": now,
    }
    intake_dir = task_intake_dir(hermes_home)
    _append_jsonl(intake_dir / "task_ledger.jsonl", [row])
    _append_jsonl(intake_dir / "sheet_outbox.jsonl", [row])


def recover_task_intake_pending(hermes_home: Path) -> dict[str, int]:
    intake_dir = task_intake_dir(hermes_home)
    ledger_path = intake_dir / "task_ledger.jsonl"
    outbox_path = intake_dir / "sheet_outbox.jsonl"
    task_rows = [
        row
        for row in _read_jsonl(ledger_path)
        if row.get("event") == "task_detected" and row.get("task_id")
    ]
    outbox_ids = _existing_task_ids(outbox_path, event_name="sheet_write_required")
    finished = _outbox_finished_task_ids(outbox_path)
    repaired_rows: list[dict[str, Any]] = []
    for row in task_rows:
        task_id = str(row.get("task_id") or "")
        if not task_id or task_id in outbox_ids or task_id in finished:
            continue
        repaired_rows.append(
            {
                **row,
                "event": "sheet_write_required",
                "status": "pending",
                "sheet_status": "pending",
                "updated_at": _now_iso(),
            }
        )
    _append_jsonl(outbox_path, repaired_rows)
    return {
        "tasks_seen": len(task_rows),
        "repaired_outbox": len(repaired_rows),
        "sheet_pending": len(pending_task_sheet_outbox_records(hermes_home)),
    }
