from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import GatewayConfig, HomeChannel, Platform, PlatformConfig
from gateway.platforms.base import SendResult
from gateway.run import GatewayRunner
from gateway.session import SessionSource


def _make_source() -> SessionSource:
    return SessionSource(
        platform=Platform.SLACK,
        chat_id="C123",
        chat_type="channel",
        user_id="U123",
        thread_id="111.222",
    )


def _make_telegram_group_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-1003716216649",
        chat_type="group",
        user_id="10954083",
        thread_id="644",
    )


def _make_telegram_dm_source() -> SessionSource:
    return SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="10954083",
        chat_type="dm",
        user_id="10954083",
        thread_id=None,
    )


def _make_runner(extra=None):
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={
            Platform.SLACK: PlatformConfig(enabled=True, token="***", extra=extra or {})
        }
    )
    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=SendResult(success=True, message_id="public-1"))
    adapter.send_private_notice = AsyncMock(return_value=SendResult(success=True, message_id="private-1"))
    runner.adapters = {Platform.SLACK: adapter}
    return runner, adapter


def _make_telegram_runner(extra=None):
    runner = object.__new__(GatewayRunner)
    runner.config = GatewayConfig(
        platforms={
            Platform.TELEGRAM: PlatformConfig(
                enabled=True,
                token="***",
                home_channel=HomeChannel(
                    platform=Platform.TELEGRAM,
                    chat_id="10954083",
                    name="Home",
                    thread_id="777",
                ),
                extra=extra or {},
            )
        }
    )
    adapter = MagicMock()
    adapter.send = AsyncMock(return_value=SendResult(success=True, message_id="home-1"))
    adapter.send_private_notice = AsyncMock(return_value=SendResult(success=True, message_id="private-1"))
    runner.adapters = {Platform.TELEGRAM: adapter}
    runner._owner_provider_alert_last_sent = {}
    runner._credit_monitor_last_band_by_provider = {}
    return runner, adapter


@pytest.mark.asyncio
async def test_deliver_platform_notice_uses_private_delivery_when_configured():
    runner, adapter = _make_runner(extra={"notice_delivery": "private"})

    await runner._deliver_platform_notice(_make_source(), "hello")

    adapter.send_private_notice.assert_awaited_once_with(
        "C123",
        "U123",
        "hello",
        metadata={"thread_id": "111.222"},
    )
    adapter.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_deliver_platform_notice_falls_back_to_public_when_private_fails():
    runner, adapter = _make_runner(extra={"notice_delivery": "private"})
    adapter.send_private_notice = AsyncMock(return_value=SendResult(success=False, error="nope"))

    await runner._deliver_platform_notice(_make_source(), "hello")

    adapter.send.assert_awaited_once_with("C123", "hello", metadata={"thread_id": "111.222"})


@pytest.mark.asyncio
async def test_deliver_platform_notice_uses_public_delivery_by_default():
    runner, adapter = _make_runner()

    await runner._deliver_platform_notice(_make_source(), "hello")

    adapter.send.assert_awaited_once_with("C123", "hello", metadata={"thread_id": "111.222"})
    adapter.send_private_notice.assert_not_awaited()


@pytest.mark.asyncio
async def test_credit_notice_routes_to_telegram_home_channel_not_source_group():
    runner, adapter = _make_telegram_runner()

    await runner._deliver_platform_notice(
        _make_telegram_group_source(),
        "✕ Credit access paused · run /credits to top up",
    )

    adapter.send.assert_awaited_once_with(
        "10954083",
        "✕ Credit access paused · run /credits to top up",
        metadata={"thread_id": "777"},
    )
    adapter.send_private_notice.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_billing_alert_routes_to_home_channel_not_source_group(monkeypatch, tmp_path):
    runner, adapter = _make_telegram_runner()
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)

    await runner._send_owner_provider_billing_alert(
        Platform.TELEGRAM,
        "Billing or credits exhausted: Error code: 402 - This request requires more credits.",
    )

    adapter.send.assert_awaited_once()
    args, kwargs = adapter.send.call_args
    assert args[0] == "10954083"
    assert "credits alert" in args[1].lower()
    assert "public chat was sanitized" in args[1].lower()
    assert "Error code" not in args[1]
    assert kwargs == {"metadata": {"thread_id": "777"}}


@pytest.mark.asyncio
async def test_public_telegram_technical_notice_routes_to_home_channel_not_source_group():
    runner, adapter = _make_telegram_runner()
    source = _make_telegram_group_source()
    content = (
        "⚠️ База: запись в Google Sheet не подтверждена. "
        "NotebookLM — аутентификация протухла, Google Sheets — OAuth не настроен."
    )

    await runner._deliver_platform_notice(source, content)

    adapter.send.assert_awaited_once_with(
        "10954083",
        content,
        metadata={"thread_id": "777"},
    )
    adapter.send_private_notice.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_telegram_technical_notice_is_suppressed_without_home_channel():
    runner, adapter = _make_telegram_runner()
    runner.config.platforms[Platform.TELEGRAM].home_channel = None

    await runner._deliver_platform_notice(
        _make_telegram_group_source(),
        "Google Sheets OAuth не настроен — запись в Knowledge Base пропущена.",
    )

    adapter.send.assert_not_awaited()
    adapter.send_private_notice.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_billing_alert_is_capped_to_one_per_day(monkeypatch, tmp_path):
    runner, adapter = _make_telegram_runner()
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    now = {"epoch": 1_750_000_000.0, "monotonic": 10_000.0}
    monkeypatch.setattr(gateway_run.time, "time", lambda: now["epoch"])
    monkeypatch.setattr(gateway_run.time, "monotonic", lambda: now["monotonic"])
    message = "Billing or credits exhausted: Error code: 402 - This request requires more credits."

    assert await runner._send_owner_provider_billing_alert(Platform.TELEGRAM, message) is True

    now["epoch"] += 3600.0
    now["monotonic"] += 3600.0

    assert await runner._send_owner_provider_billing_alert(Platform.TELEGRAM, message) is False
    assert adapter.send.await_count == 1

    now["epoch"] += 24 * 60 * 60 + 1
    now["monotonic"] += 24 * 60 * 60 + 1

    assert await runner._send_owner_provider_billing_alert(Platform.TELEGRAM, message) is True
    assert adapter.send.await_count == 2


@pytest.mark.asyncio
async def test_provider_billing_alert_daily_cap_survives_runner_restart(monkeypatch, tmp_path):
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    now = {"epoch": 1_750_000_000.0, "monotonic": 20_000.0}
    monkeypatch.setattr(gateway_run.time, "time", lambda: now["epoch"])
    monkeypatch.setattr(gateway_run.time, "monotonic", lambda: now["monotonic"])
    message = "Billing or credits exhausted: Error code: 402 - This request requires more credits."

    runner, adapter = _make_telegram_runner()
    assert await runner._send_owner_provider_billing_alert(Platform.TELEGRAM, message) is True
    assert adapter.send.await_count == 1

    now["epoch"] += 3600.0
    now["monotonic"] += 3600.0
    restarted_runner, restarted_adapter = _make_telegram_runner()

    assert await restarted_runner._send_owner_provider_billing_alert(Platform.TELEGRAM, message) is False
    restarted_adapter.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_provider_billing_alert_daily_cap_also_suppresses_credit_monitor(monkeypatch, tmp_path):
    runner, adapter = _make_telegram_runner()
    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    now = {"epoch": 1_750_000_000.0, "monotonic": 30_000.0}
    monkeypatch.setattr(gateway_run.time, "time", lambda: now["epoch"])
    monkeypatch.setattr(gateway_run.time, "monotonic", lambda: now["monotonic"])
    monkeypatch.setattr(
        gateway_run,
        "fetch_account_usage",
        lambda provider: SimpleNamespace(
            provider=provider,
            details=("Credits balance: $2.50",),
        ),
    )
    message = "Billing or credits exhausted: Error code: 402 - This request requires more credits."

    assert await runner._send_owner_provider_billing_alert(Platform.TELEGRAM, message) is True

    now["epoch"] += 3600.0
    now["monotonic"] += 3600.0
    await runner._run_credit_monitor_once(
        "openrouter",
        Platform.TELEGRAM,
        low_usd=10.0,
        critical_usd=3.0,
    )

    assert adapter.send.await_count == 1


def test_exec_approval_target_routes_telegram_group_to_home_channel():
    runner, adapter = _make_telegram_runner()
    source = _make_telegram_group_source()

    chat_id, metadata = runner._exec_approval_delivery_target(
        source,
        fallback_chat_id=source.chat_id,
        fallback_metadata={"thread_id": source.thread_id},
        adapter=adapter,
    )

    assert chat_id == "10954083"
    assert metadata == {"thread_id": "777"}


def test_exec_approval_target_rejects_telegram_group_without_home_channel():
    runner, adapter = _make_telegram_runner()
    runner.config.platforms[Platform.TELEGRAM].home_channel = None
    source = _make_telegram_group_source()

    with pytest.raises(RuntimeError, match="operator home channel"):
        runner._exec_approval_delivery_target(
            source,
            fallback_chat_id=source.chat_id,
            fallback_metadata={"thread_id": source.thread_id},
            adapter=adapter,
        )


def test_exec_approval_target_rejects_telegram_group_when_home_is_same_topic():
    runner, adapter = _make_telegram_runner()
    source = _make_telegram_group_source()
    runner.config.platforms[Platform.TELEGRAM].home_channel = HomeChannel(
        platform=Platform.TELEGRAM,
        chat_id=source.chat_id,
        name="General",
        thread_id=source.thread_id,
    )

    with pytest.raises(RuntimeError, match="operator home channel"):
        runner._exec_approval_delivery_target(
            source,
            fallback_chat_id=source.chat_id,
            fallback_metadata={"thread_id": source.thread_id},
            adapter=adapter,
        )


def test_exec_approval_target_keeps_telegram_dm_fallback_without_home_channel():
    runner, adapter = _make_telegram_runner()
    runner.config.platforms[Platform.TELEGRAM].home_channel = None
    source = _make_telegram_dm_source()

    chat_id, metadata = runner._exec_approval_delivery_target(
        source,
        fallback_chat_id=source.chat_id,
        fallback_metadata=None,
        adapter=adapter,
    )

    assert chat_id == "10954083"
    assert metadata is None
