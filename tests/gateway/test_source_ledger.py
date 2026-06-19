import json

import gateway.run as gateway_run
from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource
from gateway.source_ledger import (
    recover_source_intake_pending,
    record_link_summary_result,
    record_link_summary_sources,
    source_intake_dir,
)


def _read_jsonl(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def _link_summary_event(text: str) -> MessageEvent:
    event = MessageEvent(
        text=text,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="-1001",
            thread_id="777",
            chat_type="group",
            user_id="12345",
        ),
        message_id="msg-42",
    )
    event.telegram_interaction_intent = "link_summary"
    event.telegram_link_summary_requires_sheet_write = True
    return event


def _reply_link_summary_event(text: str, reply_to_text: str) -> MessageEvent:
    event = _link_summary_event(text)
    event.message_id = "trigger-43"
    event.reply_to_message_id = "source-7"
    event.reply_to_text = reply_to_text
    return event


def test_record_link_summary_sources_writes_ledger_and_sheet_outbox(tmp_path):
    event = _link_summary_event(
        "Please process https://youtu.be/abc123 and https://example.com/a?x=1. "
        "Context link: https://t.me/c/3716216649/2895"
    )

    records = record_link_summary_sources(tmp_path, event)

    assert [record["url_or_ref"] for record in records] == [
        "https://youtu.be/abc123",
        "https://example.com/a?x=1",
    ]
    assert getattr(event, "telegram_source_ledger_ids") == [
        records[0]["source_id"],
        records[1]["source_id"],
    ]

    intake_dir = source_intake_dir(tmp_path)
    ledger_rows = _read_jsonl(intake_dir / "source_ledger.jsonl")
    assert [row["event"] for row in ledger_rows] == ["source_discovered", "source_discovered"]
    assert {row["status"] for row in ledger_rows} == {"queued"}
    assert {row["sheet_status"] for row in ledger_rows} == {"pending"}
    assert {row["thread_id"] for row in ledger_rows} == {"777"}
    assert all(row["done"] is False for row in ledger_rows)

    outbox_rows = _read_jsonl(intake_dir / "sheet_outbox.jsonl")
    assert [row["event"] for row in outbox_rows] == ["sheet_write_required", "sheet_write_required"]
    assert {row["status"] for row in outbox_rows} == {"pending"}
    assert {row["source_id"] for row in outbox_rows} == {record["source_id"] for record in records}


def test_record_link_summary_sources_is_idempotent_for_duplicate_source(tmp_path):
    event = _link_summary_event("https://example.com/source")

    first = record_link_summary_sources(tmp_path, event)
    second = record_link_summary_sources(tmp_path, event)

    assert first[0]["source_id"] == second[0]["source_id"]

    intake_dir = source_intake_dir(tmp_path)
    ledger_rows = _read_jsonl(intake_dir / "source_ledger.jsonl")
    assert [row["event"] for row in ledger_rows] == ["source_discovered"]

    outbox_rows = _read_jsonl(intake_dir / "sheet_outbox.jsonl")
    assert [row["event"] for row in outbox_rows] == ["sheet_write_required"]


def test_record_link_summary_sources_repairs_missing_outbox_for_existing_source(tmp_path):
    event = _link_summary_event("https://example.com/source")

    first = record_link_summary_sources(tmp_path, event)
    intake_dir = source_intake_dir(tmp_path)
    outbox_path = intake_dir / "sheet_outbox.jsonl"
    outbox_path.unlink()

    second = record_link_summary_sources(tmp_path, event)

    assert first[0]["source_id"] == second[0]["source_id"]

    ledger_rows = _read_jsonl(intake_dir / "source_ledger.jsonl")
    assert [row["event"] for row in ledger_rows] == ["source_discovered"]

    outbox_rows = _read_jsonl(outbox_path)
    assert [row["event"] for row in outbox_rows] == ["sheet_write_required"]
    assert outbox_rows[0]["source_id"] == first[0]["source_id"]


def test_reply_to_source_uses_replied_message_as_source_identity(tmp_path):
    original = _link_summary_event("https://example.com/source")
    original.message_id = "source-7"
    reply = _reply_link_summary_event("@AiVocadoHermes_bot сделай конспект", "https://example.com/source")

    original_records = record_link_summary_sources(tmp_path, original)
    reply_records = record_link_summary_sources(tmp_path, reply)

    assert reply_records[0]["source_id"] == original_records[0]["source_id"]
    assert reply_records[0]["message_id"] == "source-7"
    assert reply_records[0]["trigger_message_id"] == "trigger-43"

    intake_dir = source_intake_dir(tmp_path)
    outbox_rows = _read_jsonl(intake_dir / "sheet_outbox.jsonl")
    assert [row["event"] for row in outbox_rows] == ["sheet_write_required"]


def test_record_link_summary_result_keeps_sheet_pending_when_write_missing(tmp_path):
    event = _link_summary_event("https://example.com/source")
    records = record_link_summary_sources(tmp_path, event)

    record_link_summary_result(
        tmp_path,
        event,
        response_text="Конспект готов.",
        sheet_write_attempted=False,
    )

    intake_dir = source_intake_dir(tmp_path)
    ledger_rows = _read_jsonl(intake_dir / "source_ledger.jsonl")
    result_row = ledger_rows[-1]
    assert result_row["event"] == "summary_created"
    assert result_row["source_id"] == records[0]["source_id"]
    assert result_row["status"] == "published_without_save"
    assert result_row["sheet_status"] == "pending"
    assert result_row["done"] is False

    outbox_rows = _read_jsonl(intake_dir / "sheet_outbox.jsonl")
    assert outbox_rows[-1]["event"] == "sheet_write_missing"
    assert outbox_rows[-1]["source_id"] == records[0]["source_id"]
    assert outbox_rows[-1]["status"] == "pending"


def test_record_link_summary_result_marks_sheet_attempt_without_done(tmp_path):
    event = _link_summary_event("https://example.com/source")
    records = record_link_summary_sources(tmp_path, event)

    record_link_summary_result(
        tmp_path,
        event,
        response_text="Конспект готов и строка добавлена.",
        sheet_write_attempted=True,
    )

    intake_dir = source_intake_dir(tmp_path)
    ledger_rows = _read_jsonl(intake_dir / "source_ledger.jsonl")
    result_row = ledger_rows[-1]
    assert result_row["event"] == "summary_created"
    assert result_row["source_id"] == records[0]["source_id"]
    assert result_row["status"] == "summary_created"
    assert result_row["sheet_status"] == "write_attempted"
    assert result_row["done"] is False

    outbox_rows = _read_jsonl(intake_dir / "sheet_outbox.jsonl")
    assert outbox_rows[-1]["event"] == "sheet_write_attempted"
    assert outbox_rows[-1]["source_id"] == records[0]["source_id"]
    assert outbox_rows[-1]["status"] == "attempted"


def test_recover_source_intake_repairs_missing_outbox_after_restart(tmp_path):
    event = _link_summary_event("https://example.com/source")
    records = record_link_summary_sources(tmp_path, event)
    intake_dir = source_intake_dir(tmp_path)
    outbox_path = intake_dir / "sheet_outbox.jsonl"
    outbox_path.unlink()

    summary = recover_source_intake_pending(tmp_path)

    assert summary["repaired_outbox"] == 1
    assert summary["recovery_required"] == 1

    outbox_rows = _read_jsonl(outbox_path)
    assert [row["event"] for row in outbox_rows] == ["sheet_write_required"]
    assert outbox_rows[0]["source_id"] == records[0]["source_id"]

    ledger_rows = _read_jsonl(intake_dir / "source_ledger.jsonl")
    assert ledger_rows[-1]["event"] == "recovery_required"
    assert ledger_rows[-1]["source_id"] == records[0]["source_id"]
    assert ledger_rows[-1]["status"] == "recovery_pending"
    assert ledger_rows[-1]["recovery_reason"] == "source_processing_incomplete"


def test_recover_source_intake_marks_pending_sheet_write_after_restart(tmp_path):
    event = _link_summary_event("https://example.com/source")
    records = record_link_summary_sources(tmp_path, event)
    record_link_summary_result(
        tmp_path,
        event,
        response_text="Конспект готов.",
        sheet_write_attempted=False,
    )

    summary = recover_source_intake_pending(tmp_path)

    assert summary["repaired_outbox"] == 0
    assert summary["recovery_required"] == 1

    intake_dir = source_intake_dir(tmp_path)
    ledger_rows = _read_jsonl(intake_dir / "source_ledger.jsonl")
    assert ledger_rows[-1]["event"] == "recovery_required"
    assert ledger_rows[-1]["source_id"] == records[0]["source_id"]
    assert ledger_rows[-1]["status"] == "recovery_pending"
    assert ledger_rows[-1]["recovery_reason"] == "sheet_write_pending"


def test_recover_source_intake_is_idempotent(tmp_path):
    event = _link_summary_event("https://example.com/source")
    record_link_summary_sources(tmp_path, event)
    record_link_summary_result(
        tmp_path,
        event,
        response_text="Конспект готов.",
        sheet_write_attempted=False,
    )

    first = recover_source_intake_pending(tmp_path)
    second = recover_source_intake_pending(tmp_path)

    assert first["recovery_required"] == 1
    assert second["recovery_required"] == 0

    intake_dir = source_intake_dir(tmp_path)
    ledger_rows = _read_jsonl(intake_dir / "source_ledger.jsonl")
    recovery_rows = [row for row in ledger_rows if row["event"] == "recovery_required"]
    assert len(recovery_rows) == 1


def test_gateway_startup_recovery_sweeps_source_intake(monkeypatch, tmp_path):
    event = _link_summary_event("https://example.com/source")
    record_link_summary_sources(tmp_path, event)
    record_link_summary_result(
        tmp_path,
        event,
        response_text="Конспект готов.",
        sheet_write_attempted=False,
    )
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)

    summary = gateway_run._recover_source_intake_on_gateway_startup()

    assert summary["recovery_required"] == 1
    intake_dir = source_intake_dir(tmp_path)
    ledger_rows = _read_jsonl(intake_dir / "source_ledger.jsonl")
    assert ledger_rows[-1]["event"] == "recovery_required"
    assert ledger_rows[-1]["recovery_reason"] == "sheet_write_pending"
