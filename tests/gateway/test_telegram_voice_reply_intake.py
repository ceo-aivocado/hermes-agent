import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gateway.config import Platform, PlatformConfig


def _make_adapter(*, require_mention=True, allowed_chats=None, voice_user_ids=None):
    from gateway.platforms.telegram import TelegramAdapter

    extra = {
        "require_mention": require_mention,
        "allowed_chats": allowed_chats or [],
        "group_allowed_chats": allowed_chats or [],
        "allowed_topics": [],
    }
    if voice_user_ids is not None:
        extra["always_process_voice_from_user_ids"] = voice_user_ids

    adapter = object.__new__(TelegramAdapter)
    adapter.platform = Platform.TELEGRAM
    adapter.config = PlatformConfig(enabled=True, token="***", extra=extra)
    adapter._bot = SimpleNamespace(id=999, username="hermes_bot")
    adapter._message_handler = AsyncMock()
    adapter._pending_text_batches = {}
    adapter._pending_text_batch_tasks = {}
    adapter._text_batch_delay_seconds = 0.01
    adapter._text_batch_split_delay_seconds = 0.01
    adapter._mention_patterns = adapter._compile_mention_patterns()
    adapter._forum_lock = asyncio.Lock()
    adapter._forum_command_registered = set()
    adapter._active_sessions = {}
    adapter._pending_messages = {}
    adapter._max_doc_bytes = 20 * 1024 * 1024
    adapter._is_callback_user_authorized = lambda user_id, **_kw: True
    return adapter


def _mention_entity(text, mention="@hermes_bot"):
    return SimpleNamespace(type="mention", offset=text.index(mention), length=len(mention))


def _chat(chat_id=-100):
    return SimpleNamespace(id=chat_id, type="group", title="Test Group", is_forum=False)


def _user(user_id=111, name="Alice Example"):
    return SimpleNamespace(id=user_id, full_name=name, first_name=name.split()[0])


def _voice_payload(data=b"voice-bytes"):
    file_obj = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(data)))
    return SimpleNamespace(file_size=len(data), get_file=AsyncMock(return_value=file_obj))


def _text_reply_to_voice_message(text="@hermes_bot ???", *, chat_id=-100, user_id=111):
    reply_to_message = SimpleNamespace(
        message_id=2895,
        text=None,
        caption=None,
        photo=None,
        video=None,
        voice=_voice_payload(),
        audio=None,
        document=None,
        from_user=_user(user_id, "Voice Sender"),
    )
    return SimpleNamespace(
        message_id=2900,
        text=text,
        caption=None,
        entities=[_mention_entity(text)],
        caption_entities=[],
        message_thread_id=None,
        is_topic_message=False,
        chat=_chat(chat_id),
        from_user=_user(user_id),
        reply_to_message=reply_to_message,
        quote=None,
        date=None,
    )


def _voice_message(*, chat_id=-100, user_id=10954083):
    return SimpleNamespace(
        message_id=3001,
        text=None,
        caption=None,
        entities=[],
        caption_entities=[],
        message_thread_id=None,
        is_topic_message=False,
        chat=_chat(chat_id),
        from_user=_user(user_id, "Aleksandr Pogoreliy"),
        reply_to_message=None,
        date=None,
        sticker=None,
        photo=None,
        video=None,
        audio=None,
        voice=_voice_payload(),
        document=None,
    )


def test_group_voice_from_allowed_owner_bypasses_mention_requirement():
    adapter = _make_adapter(
        require_mention=True,
        allowed_chats=["-100"],
        voice_user_ids=["10954083"],
    )

    assert adapter._should_process_message(_voice_message(user_id=10954083)) is True
    assert adapter._should_process_message(_voice_message(user_id=222)) is False


def test_telegram_internal_message_link_is_not_generic_web_summary_request():
    adapter = _make_adapter(require_mention=True, allowed_chats=["-100"])
    msg = SimpleNamespace(
        text="https://t.me/c/3716216649/2895",
        caption=None,
        video=None,
        video_note=None,
        animation=None,
        document=None,
    )

    assert adapter._is_aivocado_link_request(msg) is False


def test_text_reply_to_voice_attaches_replied_voice_for_stt(monkeypatch):
    async def _run():
        adapter = _make_adapter(require_mention=True, allowed_chats=["-100"])
        adapter._ensure_forum_commands = AsyncMock()
        adapter._apply_telegram_group_observe_attribution = lambda event: event

        captured = []
        adapter._enqueue_text_event = captured.append
        monkeypatch.setattr(
            "gateway.platforms.base.cache_media_bytes",
            lambda data, filename, mime_type, default_kind: SimpleNamespace(
                path="/tmp/replied-voice.ogg",
                media_type="audio/ogg",
                kind="audio",
                display_name=filename or "voice.ogg",
                context_note=lambda: "[Replied-to audio 'voice.ogg' saved at: /tmp/replied-voice.ogg]",
            ),
        )

        update = SimpleNamespace(
            update_id=4001,
            message=_text_reply_to_voice_message(),
            effective_message=None,
        )

        await adapter._handle_text_message(update, SimpleNamespace())

        assert len(captured) == 1
        event = captured[0]
        assert event.media_urls == ["/tmp/replied-voice.ogg"]
        assert event.media_types == ["audio/ogg"]
        assert event.reply_to_message_id == "2895"

    asyncio.run(_run())
