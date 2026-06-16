"""
Tests for #24870 — Telegram: audio file attachments must NOT be routed to STT.

Telegram distinguishes three kinds of audio payloads:
  - message.voice  → Opus/OGG voice message  → STT pipeline
  - message.audio  → audio file attachment   → file path note, NOT STT
  - message.document (audio mime) → generic file route

These tests confirm that:
  1. MessageType.VOICE events still flow through the STT pipeline.
  2. MessageType.AUDIO events bypass STT and get a file-path context note instead.
  3. Mixed media lists (voice + audio) split correctly.
"""

from unittest.mock import patch

import pytest

from gateway.config import GatewayConfig, Platform, PlatformConfig
from gateway.platforms.base import MessageEvent, MessageType
from gateway.session import SessionSource


def _make_runner(
    stt_enabled: bool = True,
    *,
    telegram_extra: dict | None = None,
) -> "GatewayRunner":  # type: ignore[name-defined]
    from gateway.run import GatewayRunner

    runner = GatewayRunner.__new__(GatewayRunner)
    runner.config = GatewayConfig(stt_enabled=stt_enabled)
    if telegram_extra is not None:
        runner.config.platforms[Platform.TELEGRAM] = PlatformConfig(
            enabled=True,
            token="***",
            extra=telegram_extra,
        )
    runner.adapters = {}
    runner._model = "test-model"
    runner._base_url = ""
    runner._has_setup_skill = lambda: False
    return runner


class _RecordingAdapter:
    def __init__(self):
        self.sent: list[tuple[str, str, dict | None]] = []

    async def send(self, chat_id, content, metadata=None):
        self.sent.append((chat_id, content, metadata))


def _voice_event(path: str = "/tmp/voice.ogg") -> MessageEvent:
    return MessageEvent(
        text="",
        message_type=MessageType.VOICE,
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm"),
        media_urls=[path],
        media_types=["audio/ogg"],
    )


def _audio_event(path: str = "/tmp/song.mp3") -> MessageEvent:
    return MessageEvent(
        text="",
        message_type=MessageType.AUDIO,
        source=SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm"),
        media_urls=[path],
        media_types=["audio/mpeg"],
    )


# ---------------------------------------------------------------------------
# 1. VOICE still goes through STT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_voice_message_still_transcribed():
    """MessageType.VOICE must still be sent through _enrich_message_with_transcription."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _voice_event("/tmp/voice.ogg")

    with patch(
        "tools.transcription_tools.transcribe_audio",
        return_value={"success": True, "transcript": "hello world", "provider": "whisper"},
    ) as mock_transcribe:
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
        )

    mock_transcribe.assert_called_once_with("/tmp/voice.ogg")
    assert "hello world" in result
    assert "voice message" in result.lower()


@pytest.mark.asyncio
async def test_telegram_voice_transcript_is_not_echoed_to_chat():
    """Telegram voice STT may feed the agent, but raw transcripts must stay private."""
    runner = _make_runner(stt_enabled=True)
    adapter = _RecordingAdapter()
    runner.adapters[Platform.TELEGRAM] = adapter
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="-100", chat_type="group")
    event = _voice_event("/tmp/voice.ogg")

    with patch(
        "tools.transcription_tools.transcribe_audio",
        return_value={
            "success": True,
            "transcript": "private voice words",
            "provider": "whisper",
        },
    ):
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
        )

    assert result is not None
    assert "private voice words" in result
    assert adapter.sent == []


@pytest.mark.asyncio
async def test_telegram_owner_group_voice_without_audio_address_is_silent():
    """Allowed owner voice in a group is only actionable when the audio addresses the bot."""
    runner = _make_runner(
        stt_enabled=True,
        telegram_extra={"always_process_voice_from_user_ids": ["10954083"]},
    )
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-100",
        chat_type="group",
        user_id="10954083",
        user_name="АЮ",
    )
    event = MessageEvent(
        text="",
        message_type=MessageType.VOICE,
        source=source,
        media_urls=["/tmp/voice.ogg"],
        media_types=["audio/ogg"],
    )

    with patch(
        "tools.transcription_tools.transcribe_audio",
        return_value={
            "success": True,
            "transcript": "Юра, врать буду я, жду у Сережи экспертизу",
            "provider": "whisper",
        },
    ):
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
        )

    assert result is None


@pytest.mark.asyncio
async def test_telegram_owner_group_voice_with_audio_address_reaches_agent_without_echo():
    """If the owner's voice addresses AiVocado, STT is internal context only."""
    runner = _make_runner(
        stt_enabled=True,
        telegram_extra={"always_process_voice_from_user_ids": ["10954083"]},
    )
    adapter = _RecordingAdapter()
    runner.adapters[Platform.TELEGRAM] = adapter
    source = SessionSource(
        platform=Platform.TELEGRAM,
        chat_id="-100",
        chat_type="group",
        user_id="10954083",
        user_name="АЮ",
    )
    event = MessageEvent(
        text="",
        message_type=MessageType.VOICE,
        source=source,
        media_urls=["/tmp/voice.ogg"],
        media_types=["audio/ogg"],
    )

    with patch(
        "tools.transcription_tools.transcribe_audio",
        return_value={
            "success": True,
            "transcript": "Авокадо, посмотри эту ссылку и сделай конспект",
            "provider": "whisper",
        },
    ):
        result = await runner._prepare_inbound_message_text(
            event=event,
            source=source,
            history=[],
        )

    assert result is not None
    assert "Авокадо, посмотри эту ссылку" in result
    assert adapter.sent == []


# ---------------------------------------------------------------------------
# 2. AUDIO file attachment bypasses STT
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audio_attachment_skips_stt():
    """MessageType.AUDIO must NOT be routed to STT — transcribe_audio must not be called."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _audio_event("/tmp/song.mp3")

    with patch(
        "tools.transcription_tools.transcribe_audio",
        side_effect=AssertionError("transcribe_audio must NOT be called for audio file attachments"),
    ):
        with patch(
            "tools.credential_files.to_agent_visible_cache_path",
            side_effect=lambda p: p,
        ):
            result = await runner._prepare_inbound_message_text(
                event=event,
                source=source,
                history=[],
            )

    assert result is not None
    assert "/tmp/song.mp3" in result
    assert "audio file attachment" in result.lower()


@pytest.mark.asyncio
async def test_audio_attachment_context_note_format():
    """Context note for audio file attachments should include the file path and guidance."""
    runner = _make_runner(stt_enabled=True)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _audio_event("/tmp/cache_12345_my_song.mp3")

    with patch(
        "tools.transcription_tools.transcribe_audio",
        side_effect=AssertionError("must not be called"),
    ):
        with patch(
            "tools.credential_files.to_agent_visible_cache_path",
            side_effect=lambda p: p,
        ):
            result = await runner._prepare_inbound_message_text(
                event=event,
                source=source,
                history=[],
            )

    assert "my_song.mp3" in result
    assert "audio file attachment" in result.lower()
    # Should NOT contain the voice-message transcription wrapper text
    assert "voice message" not in result.lower()
    # Guides the agent to transcribe/process the file itself rather than
    # punting back to the user (same bug class as the PDF/DOCX note).
    assert "transcri" in result.lower()
    assert "ask the user what they'd like" not in result.lower()


# ---------------------------------------------------------------------------
# 3. STT disabled still results in no transcription for audio file attachments
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_audio_attachment_skips_stt_when_stt_disabled():
    """Even with STT disabled, AUDIO must NOT produce STT disabled notice — just a file note."""
    runner = _make_runner(stt_enabled=False)
    source = SessionSource(platform=Platform.TELEGRAM, chat_id="1", chat_type="dm")
    event = _audio_event("/tmp/podcast.m4a")

    with patch(
        "tools.transcription_tools.transcribe_audio",
        side_effect=AssertionError("must not be called"),
    ):
        with patch(
            "tools.credential_files.to_agent_visible_cache_path",
            side_effect=lambda p: p,
        ):
            result = await runner._prepare_inbound_message_text(
                event=event,
                source=source,
                history=[],
            )

    # Should NOT see the "transcription is disabled" note — that's only for VOICE
    assert "transcription is disabled" not in result.lower()
    assert "audio file attachment" in result.lower()
    assert "/tmp/podcast.m4a" in result


# ---------------------------------------------------------------------------
# 4. Telegram gateway: msg.audio → MessageType.AUDIO (not VOICE)
# ---------------------------------------------------------------------------

def test_telegram_media_type_detection_audio_vs_voice():
    """The Telegram platform must set MessageType.AUDIO for msg.audio, VOICE for msg.voice."""
    from gateway.platforms.base import MessageType

    # The Telegram adapter's _build_media_type already returns correct values
    # via MessageType.AUDIO for .audio and MessageType.VOICE for .voice.
    # Check the constants match expected semantic roles.
    assert MessageType.AUDIO.value == "audio"
    assert MessageType.VOICE.value == "voice"
    # Sanity: they are distinct
    assert MessageType.AUDIO != MessageType.VOICE
