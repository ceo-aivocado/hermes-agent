from datetime import datetime, timezone

from agent.account_usage import AccountUsageSnapshot
from gateway.run import _build_credit_monitor_notice


def test_credit_monitor_builds_home_only_warning_for_low_balance():
    snapshot = AccountUsageSnapshot(
        provider="openrouter",
        source="credits_api",
        fetched_at=datetime.now(timezone.utc),
        details=("Credits balance: $4.62",),
    )

    band, message = _build_credit_monitor_notice(snapshot, low_usd=10.0, critical_usd=3.0)

    assert band == "low"
    assert "OpenRouter" in message
    assert "$4.62" in message
    assert "home" not in message.lower()
    assert "openrouter.ai/settings/credits" not in message


def test_credit_monitor_critical_band_overrides_low_band():
    snapshot = AccountUsageSnapshot(
        provider="openrouter",
        source="credits_api",
        fetched_at=datetime.now(timezone.utc),
        details=("Credits balance: $2.50",),
    )

    band, message = _build_credit_monitor_notice(snapshot, low_usd=10.0, critical_usd=3.0)

    assert band == "critical"
    assert "$2.50" in message


def test_credit_monitor_returns_empty_when_balance_is_healthy_or_unknown():
    healthy = AccountUsageSnapshot(
        provider="openrouter",
        source="credits_api",
        fetched_at=datetime.now(timezone.utc),
        details=("Credits balance: $50.00",),
    )
    unknown = AccountUsageSnapshot(
        provider="openrouter",
        source="credits_api",
        fetched_at=datetime.now(timezone.utc),
        details=("API key usage: $12.50 total",),
    )

    assert _build_credit_monitor_notice(healthy, low_usd=10.0, critical_usd=3.0) == (None, "")
    assert _build_credit_monitor_notice(unknown, low_usd=10.0, critical_usd=3.0) == (None, "")
