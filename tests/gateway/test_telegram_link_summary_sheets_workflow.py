import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import GatewayConfig, Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource


def _bootstrap_runner(monkeypatch, tmp_path):
    runner = gateway_run.GatewayRunner(GatewayConfig())
    runner.adapters = {}
    runner._running_agents = {}
    runner._running_agents_ts = {}
    runner._pending_messages = {}
    runner._pending_approvals = {}
    runner._is_user_authorized = lambda _source: True
    runner._set_session_env = lambda _context: None
    runner._handle_active_session_busy_message = AsyncMock(return_value=False)
    runner._session_db = MagicMock()
    runner._recover_telegram_topic_thread_id = lambda _source: None
    runner._cache_session_source = lambda _key, _source: None
    runner._is_session_run_current = lambda _key, _gen: True
    runner._begin_session_run_generation = lambda _key: 1
    runner._reply_anchor_for_event = lambda _event: None
    runner._get_guild_id = lambda _event: None
    runner._should_send_voice_reply = lambda *_a, **_kw: False
    runner.hooks = MagicMock()
    runner.hooks.emit = AsyncMock()

    now = datetime.now()
    runner.session_store = MagicMock()
    runner.session_store.get_or_create_session.return_value = SessionEntry(
        session_key="agent:main:telegram:group:-1001:12345",
        session_id="sess-link-summary",
        created_at=now - timedelta(minutes=5),
        updated_at=now,
        platform=Platform.TELEGRAM,
        chat_type="group",
    )
    runner.session_store.load_transcript.return_value = [
        {"role": "user", "content": "previous"},
        {"role": "assistant", "content": "previous answer"},
    ]
    runner.session_store.append_to_transcript = MagicMock()
    runner.session_store.update_session = MagicMock()

    monkeypatch.setattr(gateway_run, "_hermes_home", tmp_path)
    monkeypatch.setattr(
        gateway_run, "_resolve_runtime_agent_kwargs", lambda: {"api_key": "fake"}
    )
    monkeypatch.setattr(
        "agent.model_metadata.get_model_context_length",
        lambda *_args, **_kwargs: 100_000,
    )
    return runner


def _link_summary_event() -> MessageEvent:
    event = MessageEvent(
        text=(
            "[Telegram external link summary request]\n"
            "Fetch/read the external source(s), write the Google Sheet row.\n\n"
            "https://www.youtube.com/watch?v=8HjIfT2HYII4"
        ),
        source=SessionSource(
            platform=Platform.TELEGRAM,
            chat_id="-1001",
            chat_type="group",
            user_id="12345",
        ),
        message_id="msg-42",
    )
    event.auto_skill = "google-workspace"
    event.force_auto_skill_injection = True
    event.telegram_interaction_intent = "link_summary"
    event.telegram_link_summary_requires_sheet_write = True
    return event


def _read_source_intake_jsonl(tmp_path, filename):
    path = Path(tmp_path) / "source_intake" / filename
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.mark.asyncio
async def test_link_summary_forces_google_workspace_skill_in_existing_session(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)

    skill_dir = Path(tmp_path) / "skills" / "productivity" / "google-workspace"
    monkeypatch.setattr(
        "agent.skill_commands._load_skill_payload",
        lambda name, task_id=None: ("skill body https://docs.example/skill", skill_dir, "Google Workspace")
        if name == "google-workspace"
        else None,
    )
    monkeypatch.setattr(
        "agent.skill_commands._build_skill_message",
        lambda payload, directory, note: f"[SKILL:{directory.name}]\n{note}\n{payload}",
    )

    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "Конспект готов.",
            "messages": [{"role": "user", "content": "processed"}],
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
        }
    )

    await runner._handle_message_with_agent(
        _link_summary_event(),
        _link_summary_event().source,
        "agent:main:telegram:group:-1001:12345",
        1,
    )

    message = runner._run_agent.await_args.kwargs["message"]
    assert "[SKILL:google-workspace]" in message
    assert "Google Workspace" in message
    assert "https://www.youtube.com/watch?v=8HjIfT2HYII4" in message

    ledger_rows = _read_source_intake_jsonl(tmp_path, "source_ledger.jsonl")
    discovered_urls = [row["url_or_ref"] for row in ledger_rows if row["event"] == "source_discovered"]
    assert discovered_urls == ["https://www.youtube.com/watch?v=8HjIfT2HYII4"]


@pytest.mark.asyncio
async def test_link_summary_records_source_before_agent_run(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)

    async def _run_agent_with_ledger_assertion(**_kwargs):
        ledger_rows = _read_source_intake_jsonl(tmp_path, "source_ledger.jsonl")
        assert ledger_rows[0]["event"] == "source_discovered"
        assert ledger_rows[0]["url_or_ref"] == "https://www.youtube.com/watch?v=8HjIfT2HYII4"
        assert ledger_rows[0]["status"] == "queued"
        assert ledger_rows[0]["sheet_status"] == "pending"
        assert ledger_rows[0]["done"] is False
        return {
            "final_response": "Конспект готов.",
            "messages": [{"role": "assistant", "content": "Конспект готов."}],
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
        }

    runner._run_agent = AsyncMock(side_effect=_run_agent_with_ledger_assertion)

    response = await runner._handle_message_with_agent(
        _link_summary_event(),
        _link_summary_event().source,
        "agent:main:telegram:group:-1001:12345",
        1,
    )

    assert response is not None
    assert "База: запись в Google Sheet не подтверждена" in response

    ledger_rows = _read_source_intake_jsonl(tmp_path, "source_ledger.jsonl")
    assert [row["event"] for row in ledger_rows] == ["source_discovered", "summary_created"]
    assert ledger_rows[-1]["status"] == "published_without_save"
    assert ledger_rows[-1]["sheet_status"] == "pending"
    assert ledger_rows[-1]["done"] is False

    outbox_rows = _read_source_intake_jsonl(tmp_path, "sheet_outbox.jsonl")
    assert [row["event"] for row in outbox_rows] == [
        "sheet_write_required",
        "sheet_write_missing",
    ]
    assert outbox_rows[-1]["status"] == "pending"


@pytest.mark.asyncio
async def test_link_summary_surfaces_missing_google_sheet_write(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "Конспект готов.",
            "messages": [
                {"role": "user", "content": "summarize url"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_fetch",
                            "function": {
                                "name": "web_fetch",
                                "arguments": '{"url":"https://www.youtube.com/watch?v=8HjIfT2HYII4"}',
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_fetch", "content": "source text"},
                {"role": "assistant", "content": "Конспект готов."},
            ],
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
        }
    )

    response = await runner._handle_message_with_agent(
        _link_summary_event(),
        _link_summary_event().source,
        "agent:main:telegram:group:-1001:12345",
        1,
    )

    assert response is not None
    assert "Конспект готов." in response
    assert "База: запись в Google Sheet не подтверждена" in response
    assert "Google Sheet write was not confirmed" not in response


@pytest.mark.asyncio
async def test_link_summary_does_not_duplicate_agent_visible_sheet_auth_block(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": (
                "Конспект готов.\n\n"
                "⚠️ KB/Sheet\n"
                "Google-авторизация не настроена — запись в Knowledge Base пропущена. "
                "Когда настроим — догоним backlog."
            ),
            "messages": [
                {"role": "user", "content": "summarize url"},
                {"role": "assistant", "content": "Конспект готов. Google-авторизация не настроена."},
            ],
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
        }
    )

    response = await runner._handle_message_with_agent(
        _link_summary_event(),
        _link_summary_event().source,
        "agent:main:telegram:group:-1001:12345",
        1,
    )

    assert response is not None
    assert response.count("KB/Sheet") == 1
    assert "Google-авторизация не настроена" in response
    assert "Google Sheet write was not confirmed" not in response
    assert "База: запись в Google Sheet не подтверждена" not in response


@pytest.mark.asyncio
async def test_link_summary_does_not_warn_when_sheet_append_tool_call_exists(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "Конспект готов и строка добавлена.",
            "messages": [
                {"role": "user", "content": "summarize url"},
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_sheet",
                            "function": {
                                "name": "terminal",
                                "arguments": (
                                    '{"cmd":"python skills/productivity/google-workspace/scripts/'
                                    'google_api.py sheets append SHEET_ID Sheet1!A:C --values '
                                    '\\"[[\\\\\\"url\\\\\\",\\\\\\"summary\\\\\\"]]\\\""}'
                                ),
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_sheet", "content": '{"status":"ok"}'},
                {"role": "assistant", "content": "Конспект готов и строка добавлена."},
            ],
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
        }
    )

    response = await runner._handle_message_with_agent(
        _link_summary_event(),
        _link_summary_event().source,
        "agent:main:telegram:group:-1001:12345",
        1,
    )

    assert response == "Конспект готов и строка добавлена."
    outbox_rows = _read_source_intake_jsonl(tmp_path, "sheet_outbox.jsonl")
    assert outbox_rows[-1]["event"] == "sheet_write_attempted"
    assert outbox_rows[-1]["status"] == "attempted"
