import json
import time
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

import gateway.run as gateway_run
from gateway.config import GatewayConfig, Platform
from gateway.platforms.base import MessageEvent
from gateway.session import SessionEntry, SessionSource
from gateway.source_ledger import (
    pending_source_replay_records,
    recover_source_intake_pending,
    record_link_summary_result,
    record_link_summary_sources,
)


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


class _FakeSheetAppendProcess:
    def __init__(self, *, returncode=0, stdout='{"updatedCells": 9}', stderr=""):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr

    async def communicate(self):
        return self._stdout.encode(), self._stderr.encode()


class _FakeGoogleSheetsResponse:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return b'{"updates":{"updatedCells":9}}'


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
    ledger_rows = _read_source_intake_jsonl(tmp_path, "source_ledger.jsonl")
    assert ledger_rows[-1]["event"] == "summary_created"
    assert ledger_rows[-1]["sheet_status"] == "succeeded"
    assert ledger_rows[-1]["done"] is True

    outbox_rows = _read_source_intake_jsonl(tmp_path, "sheet_outbox.jsonl")
    assert outbox_rows[-1]["event"] == "sheet_write_succeeded"
    assert outbox_rows[-1]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_link_summary_video_attachment_is_analyzed_before_agent(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    video_path = tmp_path / "instagram-reel.mp4"
    video_path.write_bytes(b"fake mp4")
    event = _link_summary_event()
    event.media_urls = [str(video_path)]
    event.media_types = ["video/mp4"]
    event.message_type = gateway_run.MessageType.VIDEO

    video_calls = []

    async def fake_video_analyze_tool(video_url, user_prompt, model=None):
        video_calls.append((video_url, user_prompt, model))
        return json.dumps(
            {
                "success": True,
                "analysis": "В ролике показан AI workflow и шаги настройки оркестрации.",
            }
        )

    monkeypatch.setattr("tools.vision_tools.video_analyze_tool", fake_video_analyze_tool)
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "Конспект готов и строка добавлена.",
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_sheet",
                            "function": {
                                "name": "terminal",
                                "arguments": "google_api.py sheets append",
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_sheet", "content": '{"status":"ok"}'},
            ],
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
        }
    )

    response = await runner._handle_message_with_agent(
        event,
        event.source,
        "agent:main:telegram:group:-1001:12345",
        1,
    )

    assert response == "Конспект готов и строка добавлена."
    assert video_calls and video_calls[0][0] == str(video_path)
    sent_message = runner._run_agent.await_args.kwargs["message"]
    assert "Here's what I can extract from the attached video" in sent_message
    assert "AI workflow" in sent_message
    assert "instagram-reel.mp4" in sent_message


@pytest.mark.asyncio
async def test_link_summary_uses_observed_video_path_from_channel_context(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    video_path = tmp_path / "observed-instagram-reel.mp4"
    video_path.write_bytes(b"fake mp4")
    event = _link_summary_event()
    event.channel_context = f"[Previous observed message]\n[video 'reel.mp4' saved at: {video_path}]"

    video_calls = []

    async def fake_video_analyze_tool(video_url, user_prompt, model=None):
        video_calls.append(video_url)
        return json.dumps(
            {
                "success": True,
                "analysis": "Observed Reel shows a practical AI orchestration setup.",
            }
        )

    monkeypatch.setattr("tools.vision_tools.video_analyze_tool", fake_video_analyze_tool)
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "Конспект готов и строка добавлена.",
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "id": "call_sheet",
                            "function": {
                                "name": "terminal",
                                "arguments": "google_api.py sheets append",
                            },
                        }
                    ],
                },
                {"role": "tool", "tool_call_id": "call_sheet", "content": '{"status":"ok"}'},
            ],
            "tools": [],
            "history_offset": 0,
            "last_prompt_tokens": 0,
        }
    )

    response = await runner._handle_message_with_agent(
        event,
        event.source,
        "agent:main:telegram:group:-1001:12345",
        1,
    )

    assert response == "Конспект готов и строка добавлена."
    assert video_calls == [str(video_path)]
    sent_message = runner._run_agent.await_args.kwargs["message"]
    assert "Observed Reel shows" in sent_message


@pytest.mark.asyncio
async def test_link_summary_keeps_sheet_failed_pending(monkeypatch, tmp_path):
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
                {"role": "tool", "tool_call_id": "call_sheet", "content": '{"error":"NOT_AUTHENTICATED"}'},
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
    assert "База: запись в Google Sheet не подтверждена" in response

    ledger_rows = _read_source_intake_jsonl(tmp_path, "source_ledger.jsonl")
    assert ledger_rows[-1]["event"] == "summary_created"
    assert ledger_rows[-1]["sheet_status"] == "failed"
    assert ledger_rows[-1]["done"] is False

    outbox_rows = _read_source_intake_jsonl(tmp_path, "sheet_outbox.jsonl")
    assert outbox_rows[-1]["event"] == "sheet_write_failed"
    assert outbox_rows[-1]["status"] == "pending"

    pending = pending_source_replay_records(tmp_path)
    assert [row["source_id"] for row in pending] == [ledger_rows[-1]["source_id"]]


@pytest.mark.asyncio
async def test_source_replay_retries_pending_sheet_write_quietly(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    event = _link_summary_event()
    records = record_link_summary_sources(tmp_path, event)
    record_link_summary_result(
        tmp_path,
        event,
        response_text="Конспект готов.",
        sheet_write_attempted=False,
    )
    recover_source_intake_pending(tmp_path)

    runner._clear_session_env = lambda _tokens: None
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "Replay записал строку.",
            "messages": [
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
            ],
            "history_offset": 0,
        }
    )

    summary = await runner._replay_source_intake_pending(limit=5)

    assert summary == {
        "queued": 1,
        "attempted": 1,
        "sheet_outbox_queued": 0,
        "sheet_outbox_attempted": 0,
        "sheet_outbox_succeeded": 0,
        "sheet_outbox_failed": 0,
        "sheet_outbox_blocked": 0,
        "sheet_write_attempted": 1,
        "sheet_write_succeeded": 1,
        "sheet_write_failed": 0,
        "failed": 0,
    }
    kwargs = runner._run_agent.await_args.kwargs
    assert kwargs["history"] == []
    assert kwargs["silent"] is True
    assert "Telegram external link summary recovery" in kwargs["message"]
    assert "Do not send a public chat reply" in kwargs["message"]
    assert records[0]["url_or_ref"] in kwargs["message"]

    ledger_rows = _read_source_intake_jsonl(tmp_path, "source_ledger.jsonl")
    assert ledger_rows[-1]["event"] == "source_replay_completed"
    assert ledger_rows[-1]["source_id"] == records[0]["source_id"]
    assert ledger_rows[-1]["sheet_status"] == "succeeded"
    assert ledger_rows[-1]["done"] is True

    outbox_rows = _read_source_intake_jsonl(tmp_path, "sheet_outbox.jsonl")
    assert outbox_rows[-1]["event"] == "sheet_write_succeeded"
    assert outbox_rows[-1]["status"] == "succeeded"


@pytest.mark.asyncio
async def test_source_replay_completes_sheet_outbox_directly_when_configured(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    event = _link_summary_event()
    records = record_link_summary_sources(tmp_path, event)
    record_link_summary_result(
        tmp_path,
        event,
        response_text="Конспект готов.",
        sheet_write_attempted=False,
    )

    script_path = tmp_path / "google_api.py"
    script_path.write_text("# fake google api", encoding="utf-8")
    monkeypatch.setenv("HERMES_SOURCE_SHEET_ID", "sheet-123")
    monkeypatch.setenv("HERMES_SOURCE_SHEET_RANGE", "Sources!A:I")
    monkeypatch.setenv("HERMES_GOOGLE_API_SCRIPT", str(script_path))

    calls = []

    async def fake_create_subprocess_exec(*args, **kwargs):
        calls.append((args, kwargs))
        return _FakeSheetAppendProcess()

    monkeypatch.setattr(gateway_run.asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
    runner._run_agent = AsyncMock()

    summary = await runner._replay_source_intake_pending(limit=5)

    assert summary["sheet_outbox_queued"] == 1
    assert summary["sheet_outbox_attempted"] == 1
    assert summary["sheet_outbox_succeeded"] == 1
    assert summary["queued"] == 0
    runner._run_agent.assert_not_called()

    args, kwargs = calls[0]
    assert args[:5] == (
        gateway_run.sys.executable,
        str(script_path),
        "sheets",
        "append",
        "sheet-123",
    )
    assert args[5] == "Sources!A:I"
    assert kwargs["stdout"] is gateway_run.asyncio.subprocess.PIPE
    values = json.loads(args[7])
    assert values[0][2] == records[0]["url_or_ref"]
    assert values[0][3] == "Конспект готов."
    assert values[0][4] == records[0]["source_id"]

    ledger_rows = _read_source_intake_jsonl(tmp_path, "source_ledger.jsonl")
    assert ledger_rows[-1]["event"] == "source_sheet_write_completed"
    assert ledger_rows[-1]["sheet_status"] == "succeeded"
    assert ledger_rows[-1]["done"] is True

    outbox_rows = _read_source_intake_jsonl(tmp_path, "sheet_outbox.jsonl")
    assert [row["event"] for row in outbox_rows[-2:]] == [
        "source_sheet_append_started",
        "sheet_write_succeeded",
    ]


@pytest.mark.asyncio
async def test_source_replay_uses_mcp_google_token_when_google_api_auth_is_missing(
    monkeypatch,
    tmp_path,
):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    event = _link_summary_event()
    records = record_link_summary_sources(tmp_path, event)
    record_link_summary_result(
        tmp_path,
        event,
        response_text="Конспект готов.",
        sheet_write_attempted=False,
    )
    token_dir = tmp_path / "mcp-tokens"
    token_dir.mkdir()
    (token_dir / "google-workspace.json").write_text(
        json.dumps(
            {
                "access_token": "ya29.mcp-access-token",
                "token_type": "Bearer",
                "scope": "openid https://www.googleapis.com/auth/spreadsheets",
                "expires_at": time.time() + 3600,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("HERMES_SOURCE_SHEET_ID", "sheet-123")
    monkeypatch.setenv("HERMES_SOURCE_SHEET_RANGE", "Sources!A:I")
    monkeypatch.setenv("HERMES_GOOGLE_API_SCRIPT", str(tmp_path / "missing-google-api.py"))

    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _FakeGoogleSheetsResponse()

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    runner._run_agent = AsyncMock()

    summary = await runner._replay_source_intake_pending(limit=5)

    assert summary["sheet_outbox_succeeded"] == 1
    assert summary["queued"] == 0
    runner._run_agent.assert_not_called()
    assert "/v4/spreadsheets/sheet-123/values/Sources%21A%3AI:append" in captured["url"]
    assert captured["headers"]["Authorization"] == "Bearer ya29.mcp-access-token"
    assert captured["body"]["values"][0][2] == records[0]["url_or_ref"]
    assert captured["body"]["values"][0][3] == "Конспект готов."
    assert captured["timeout"] > 0

    ledger_rows = _read_source_intake_jsonl(tmp_path, "source_ledger.jsonl")
    assert ledger_rows[-1]["event"] == "source_sheet_write_completed"
    assert ledger_rows[-1]["sheet_status"] == "succeeded"
    assert ledger_rows[-1]["done"] is True


@pytest.mark.asyncio
async def test_source_replay_blocks_direct_writer_when_no_usable_auth_exists(
    monkeypatch,
    tmp_path,
):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    event = _link_summary_event()
    record_link_summary_sources(tmp_path, event)
    record_link_summary_result(
        tmp_path,
        event,
        response_text="Конспект готов.",
        sheet_write_attempted=False,
    )
    monkeypatch.setenv("HERMES_SOURCE_SHEET_ID", "sheet-123")
    monkeypatch.setenv("HERMES_GOOGLE_API_SCRIPT", str(tmp_path / "missing-google-api.py"))
    runner._run_agent = AsyncMock(
        return_value={
            "final_response": "Replay did not write Sheet.",
            "messages": [],
            "history_offset": 0,
        }
    )

    summary = await runner._replay_source_intake_pending(limit=5)

    assert summary["sheet_outbox_blocked"] == 1
    assert summary["queued"] == 1
    outbox_rows = _read_source_intake_jsonl(tmp_path, "sheet_outbox.jsonl")
    blocked_rows = [row for row in outbox_rows if row["event"] == "sheet_write_blocked"]
    assert blocked_rows
    assert blocked_rows[-1]["status"] == "pending"
    assert "ya29" not in blocked_rows[-1].get("error", "")


def test_source_replay_periodic_sweep_respects_interval(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    calls = []
    runner._schedule_source_intake_replay = lambda: calls.append("scheduled") or 2
    monkeypatch.setenv("HERMES_SOURCE_REPLAY_SWEEP_INTERVAL_SECONDS", "60")

    assert runner._maybe_schedule_source_intake_replay_sweep(now=1000.0) == 2
    assert runner._maybe_schedule_source_intake_replay_sweep(now=1030.0) == 0
    assert runner._maybe_schedule_source_intake_replay_sweep(now=1061.0) == 2
    assert calls == ["scheduled", "scheduled"]


def test_source_replay_periodic_sweep_can_be_disabled(monkeypatch, tmp_path):
    runner = _bootstrap_runner(monkeypatch, tmp_path)
    runner._schedule_source_intake_replay = lambda: 1
    monkeypatch.setenv("HERMES_SOURCE_REPLAY_SWEEP_INTERVAL_SECONDS", "0")

    assert runner._maybe_schedule_source_intake_replay_sweep(now=1000.0) == 0
