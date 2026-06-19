import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from gateway.config import Platform, PlatformConfig
from gateway.platforms.base import MessageType


def _make_adapter(
    *,
    require_mention=True,
    allowed_chats=None,
    group_allowed_chats=None,
    source_intake_chats=None,
    observe_unmentioned_group_messages=False,
    voice_user_ids=None,
):
    from gateway.platforms.telegram import TelegramAdapter

    extra = {
        "require_mention": require_mention,
        "allowed_chats": allowed_chats or [],
        "group_allowed_chats": group_allowed_chats or allowed_chats or [],
        "source_intake_chats": source_intake_chats or [],
        "allowed_topics": [],
        "observe_unmentioned_group_messages": observe_unmentioned_group_messages,
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


def _group_text(text, *, chat_id=-100, user_id=111, entities=None, reply_to_text=None):
    reply_to_message = None
    if reply_to_text is not None:
        reply_to_message = SimpleNamespace(message_id=41, text=reply_to_text, caption=None)
    return SimpleNamespace(
        message_id=42,
        text=text,
        caption=None,
        entities=entities or [],
        caption_entities=[],
        message_thread_id=None,
        is_topic_message=False,
        chat=_chat(chat_id),
        from_user=_user(user_id),
        reply_to_message=reply_to_message,
        date=None,
    )


def _voice_payload(data=b"voice-bytes"):
    file_obj = SimpleNamespace(download_as_bytearray=AsyncMock(return_value=bytearray(data)))
    return SimpleNamespace(file_size=len(data), get_file=AsyncMock(return_value=file_obj))


def _group_voice(*, chat_id=-100, user_id=10954083):
    return SimpleNamespace(
        message_id=43,
        text=None,
        caption=None,
        entities=[],
        caption_entities=[],
        message_thread_id=None,
        is_topic_message=False,
        chat=_chat(chat_id),
        from_user=_user(user_id),
        reply_to_message=None,
        date=None,
        sticker=None,
        photo=None,
        video=None,
        audio=None,
        voice=_voice_payload(),
        document=None,
    )


def _group_video(*, chat_id=-100, user_id=111):
    return SimpleNamespace(
        message_id=44,
        text=None,
        caption=None,
        entities=[],
        caption_entities=[],
        message_thread_id=None,
        is_topic_message=False,
        chat=_chat(chat_id),
        from_user=_user(user_id),
        reply_to_message=None,
        date=None,
        sticker=None,
        photo=None,
        video=SimpleNamespace(file_size=1024),
        audio=None,
        voice=None,
        document=None,
        animation=None,
        video_note=None,
    )


def test_router_marks_mention_only_as_context_needed_dispatch():
    adapter = _make_adapter(require_mention=True, allowed_chats=["-100"])
    text = "@hermes_bot"
    msg = _group_text(text, entities=[_mention_entity(text)])

    decision = adapter._telegram_interaction_decision(msg, msg_type=MessageType.TEXT)

    assert decision.action == "dispatch"
    assert decision.intent == "context_needed"
    assert decision.reason == "mention_only"
    assert decision.needs_context is True


def test_router_observes_unmentioned_allowed_group_context_without_dispatch():
    adapter = _make_adapter(
        require_mention=True,
        allowed_chats=["-100"],
        group_allowed_chats=["-100"],
        observe_unmentioned_group_messages=True,
    )
    msg = _group_text("side context")

    decision = adapter._telegram_interaction_decision(msg, msg_type=MessageType.TEXT)

    assert decision.action == "observe"
    assert decision.intent == "group_context"
    assert decision.reason == "unmentioned_group_context"


def test_router_classifies_owner_voice_as_voice_stt_dispatch():
    adapter = _make_adapter(
        require_mention=True,
        allowed_chats=["-100"],
        voice_user_ids=["10954083"],
    )

    decision = adapter._telegram_interaction_decision(_group_voice(), msg_type=MessageType.VOICE)

    assert decision.action == "dispatch"
    assert decision.intent == "voice_stt"
    assert decision.reason == "owner_voice_allowlist"


def test_router_ignores_other_user_voice_without_tag_or_workflow():
    adapter = _make_adapter(
        require_mention=True,
        allowed_chats=["-100"],
        voice_user_ids=["10954083"],
    )

    decision = adapter._telegram_interaction_decision(
        _group_voice(user_id=222),
        msg_type=MessageType.VOICE,
    )

    assert decision.action == "ignore"
    assert decision.intent == "ignored"


def test_router_classifies_telegram_internal_link_for_resolver_not_summary():
    adapter = _make_adapter(require_mention=True, allowed_chats=["-100"])
    text = "@hermes_bot https://t.me/c/3716216649/2895"
    msg = _group_text(text, entities=[_mention_entity(text)])

    decision = adapter._telegram_interaction_decision(msg, msg_type=MessageType.TEXT)

    assert decision.action == "dispatch"
    assert decision.intent == "telegram_message_link"
    assert decision.reason == "telegram_internal_link"


def test_router_classifies_external_link_summary_request():
    adapter = _make_adapter(require_mention=True, allowed_chats=["-100"])
    text = "@hermes_bot https://example.com/article"
    msg = _group_text(text, entities=[_mention_entity(text)])

    decision = adapter._telegram_interaction_decision(msg, msg_type=MessageType.TEXT)

    assert decision.action == "dispatch"
    assert decision.intent == "link_summary"
    assert decision.reason == "external_link"


def test_router_classifies_direct_mention_reply_to_external_link_as_link_summary_request():
    adapter = _make_adapter(require_mention=True, allowed_chats=["-100"])
    text = "@hermes_bot сделай конспект"
    msg = _group_text(
        text,
        entities=[_mention_entity(text)],
        reply_to_text="https://example.com/article",
    )

    decision = adapter._telegram_interaction_decision(msg, msg_type=MessageType.TEXT)

    assert decision.action == "dispatch"
    assert decision.intent == "link_summary"
    assert decision.reason == "external_link"


def test_router_dispatches_unmentioned_external_link_in_allowed_group():
    adapter = _make_adapter(require_mention=True, allowed_chats=["-100"])
    msg = _group_text("https://example.com/article")

    decision = adapter._telegram_interaction_decision(msg, msg_type=MessageType.TEXT)

    assert decision.action == "dispatch"
    assert decision.intent == "link_summary"
    assert decision.reason == "external_link"


def test_router_dispatches_unmentioned_external_link_in_source_intake_group_without_allowed_chats():
    adapter = _make_adapter(
        require_mention=True,
        allowed_chats=[],
        group_allowed_chats=["-100"],
        source_intake_chats=["-100"],
    )
    msg = _group_text("https://example.com/article")

    decision = adapter._telegram_interaction_decision(msg, msg_type=MessageType.TEXT)

    assert decision.action == "dispatch"
    assert decision.intent == "link_summary"
    assert decision.reason == "external_link"


def test_router_dispatches_unmentioned_video_in_allowed_group():
    adapter = _make_adapter(require_mention=True, allowed_chats=["-100"])

    decision = adapter._telegram_interaction_decision(_group_video(), msg_type=MessageType.VIDEO)

    assert decision.action == "dispatch"
    assert decision.intent == "link_summary"
    assert decision.reason == "external_link"


def test_router_ignores_unmentioned_external_link_outside_allowed_group():
    adapter = _make_adapter(require_mention=True, allowed_chats=["-200"])
    msg = _group_text("https://example.com/article")

    decision = adapter._telegram_interaction_decision(msg, msg_type=MessageType.TEXT)

    assert decision.action == "ignore"
    assert decision.intent == "ignored"
