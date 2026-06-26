import json

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource
from gateway.task_intake import TaskIntakeRules, parse_task_intake
from gateway.task_ledger import (
    pending_task_sheet_outbox_records,
    record_task_intake,
    record_task_sheet_append_result,
    recover_task_intake_pending,
)


def _record():
    event = MessageEvent(
        text="#задача @ivan #разработка Проверить лендинг",
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


def _jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_record_task_intake_writes_ledger_and_sheet_outbox(tmp_path):
    summary = record_task_intake(tmp_path, _record())

    assert summary == {"recorded": 1, "duplicates": 0, "sheet_queued": 1, "destination_queued": 0}
    ledger_rows = _jsonl(tmp_path / "task_intake" / "task_ledger.jsonl")
    outbox_rows = _jsonl(tmp_path / "task_intake" / "sheet_outbox.jsonl")
    assert ledger_rows[0]["event"] == "task_detected"
    assert ledger_rows[0]["sheet_status"] == "pending"
    assert outbox_rows[0]["event"] == "sheet_write_required"
    assert outbox_rows[0]["status"] == "pending"


def test_same_task_does_not_duplicate_sheet_outbox(tmp_path):
    record = _record()
    first = record_task_intake(tmp_path, record)
    second = record_task_intake(tmp_path, record)

    assert first["recorded"] == 1
    assert second == {"recorded": 0, "duplicates": 1, "sheet_queued": 0, "destination_queued": 0}
    assert len(_jsonl(tmp_path / "task_intake" / "sheet_outbox.jsonl")) == 1
    assert _jsonl(tmp_path / "task_intake" / "task_ledger.jsonl")[-1]["event"] == "task_duplicate"


def test_pending_rows_survive_restart_and_failed_sheet_write_stays_pending(tmp_path):
    record = _record()
    record_task_intake(tmp_path, record)
    record_task_sheet_append_result(tmp_path, record, error="google_api.py not authenticated")

    recovered = recover_task_intake_pending(tmp_path)
    pending = pending_task_sheet_outbox_records(tmp_path)

    assert recovered["tasks_seen"] == 1
    assert recovered["repaired_outbox"] == 0
    assert recovered["sheet_pending"] == 1
    assert [row["task_id"] for row in pending] == [record.task_id]
    assert _jsonl(tmp_path / "task_intake" / "task_ledger.jsonl")[-1]["event"] == "sheet_write_failed"
