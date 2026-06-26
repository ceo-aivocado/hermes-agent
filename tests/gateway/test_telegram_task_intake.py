from unittest.mock import AsyncMock

import pytest

from gateway.config import Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionSource


def _event(text: str, *, chat_id: str = "-100") -> MessageEvent:
    return MessageEvent(
        text=text,
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id=chat_id,
            chat_type="group",
            thread_id="7",
            user_id="10954083",
            user_name="АЮ",
        ),
        message_id="42",
    )


@pytest.mark.asyncio
async def test_allowed_chat_marker_records_task_and_returns_short_ack(monkeypatch, tmp_path):
    import gateway.run as gateway_run
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("TELEGRAM_TASK_INTAKE_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_TASK_INTAKE_CHATS", "-100")
    runner._append_task_sheet_outbox_record = AsyncMock(return_value={"status": "succeeded"})

    ack = await runner._maybe_handle_task_intake(_event("#задача @ivan #разработка Проверить лендинг"))

    assert ack == "Записал задачу: @ivan / разработка / new."
    assert (tmp_path / "task_intake" / "task_ledger.jsonl").exists()


@pytest.mark.asyncio
async def test_google_failure_keeps_outbox_pending_and_returns_safe_ack(monkeypatch, tmp_path):
    import gateway.run as gateway_run
    from gateway.run import GatewayRunner
    from gateway.task_ledger import pending_task_sheet_outbox_records

    runner = object.__new__(GatewayRunner)
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("TELEGRAM_TASK_INTAKE_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_TASK_INTAKE_CHATS", "-100")
    runner._append_task_sheet_outbox_record = AsyncMock(
        return_value={"status": "failed", "error": "google_api.py not authenticated"}
    )

    ack = await runner._maybe_handle_task_intake(_event("#task @masha #content Draft post"))

    assert ack == "Записал задачу, таблица временно недоступна, поставил в очередь."
    assert "google_api.py" not in ack
    assert len(pending_task_sheet_outbox_records(tmp_path)) == 1


@pytest.mark.asyncio
async def test_missing_sheet_config_keeps_real_outbox_pending(monkeypatch, tmp_path):
    import gateway.run as gateway_run
    from gateway.run import GatewayRunner
    from gateway.task_ledger import pending_task_sheet_outbox_records

    runner = object.__new__(GatewayRunner)
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("TELEGRAM_TASK_INTAKE_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_TASK_INTAKE_CHATS", "-100")
    monkeypatch.delenv("TELEGRAM_TASK_SHEET_ID", raising=False)
    monkeypatch.delenv("HERMES_TASK_SHEET_ID", raising=False)

    ack = await runner._maybe_handle_task_intake(_event("#задача @ivan #разработка Проверить лендинг"))

    assert ack == "Записал задачу, таблица временно недоступна, поставил в очередь."
    assert len(pending_task_sheet_outbox_records(tmp_path)) == 1


@pytest.mark.asyncio
async def test_mcp_token_sheet_path_marks_outbox_succeeded(monkeypatch, tmp_path):
    import gateway.run as gateway_run
    from gateway.run import GatewayRunner
    from gateway.task_ledger import pending_task_sheet_outbox_records

    runner = object.__new__(GatewayRunner)
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("TELEGRAM_TASK_INTAKE_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_TASK_INTAKE_CHATS", "-100")
    monkeypatch.setenv("TELEGRAM_TASK_SHEET_ID", "sheet-123")
    monkeypatch.setattr(GatewayRunner, "_source_sheet_mcp_access_token", classmethod(lambda cls: "token"))
    runner._append_task_sheet_with_access_token_sync = lambda record, *, access_token: {
        "status": "succeeded",
        "returncode": 0,
        "result": '{"updates":{"updatedCells":24}}',
    }

    ack = await runner._maybe_handle_task_intake(_event("#task @masha #content Draft post"))

    assert ack == "Записал задачу: @masha / content / new."
    assert pending_task_sheet_outbox_records(tmp_path) == []


@pytest.mark.asyncio
async def test_unallowed_chat_or_missing_marker_does_nothing(monkeypatch, tmp_path):
    import gateway.run as gateway_run
    from gateway.run import GatewayRunner

    runner = object.__new__(GatewayRunner)
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setenv("TELEGRAM_TASK_INTAKE_ENABLED", "true")
    monkeypatch.setenv("TELEGRAM_TASK_INTAKE_CHATS", "-100")
    runner._append_task_sheet_outbox_record = AsyncMock(return_value={"status": "succeeded"})

    assert await runner._maybe_handle_task_intake(_event("#задача @ivan hidden", chat_id="-200")) is None
    assert await runner._maybe_handle_task_intake(_event("plain text", chat_id="-100")) is None
    runner._append_task_sheet_outbox_record.assert_not_awaited()
