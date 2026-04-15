from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.models import CodexEvent, CodexThread, OutboundMessage
from codex_telegram_gateway.service import GatewayService

from tests.unit.support import DummyCodexBridge, DummyState, DummyTelegramClient


def test_link_current_thread_creates_topic_and_binding() -> None:
    config = GatewayConfig(
        telegram_bot_token="token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )
    state = DummyState()
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Remove browser entitlement",
            status="idle",
            cwd="/Users/kangmo/sacle/src/blink",
        )
    )

    service = GatewayService(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )

    binding = service.link_current_thread()

    assert binding.codex_thread_id == "thread-1"
    assert binding.chat_id == -100100
    assert binding.message_thread_id == 1
    assert binding.topic_name == "(blink) Remove browser entitlement"
    assert binding.project_id == "/Users/kangmo/sacle/src/blink"
    assert state.get_binding_by_thread("thread-1") == binding
    assert telegram.created_topics == [(-100100, "(blink) Remove browser entitlement")]
    lifecycle = state.get_topic_lifecycle("thread-1")
    assert lifecycle is not None
    assert lifecycle.chat_id == -100100
    assert lifecycle.message_thread_id == 1
    assert lifecycle.bound_at is not None


def test_link_loaded_threads_reuses_existing_binding() -> None:
    config = GatewayConfig(
        telegram_bot_token="token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )
    state = DummyState()
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Remove browser entitlement",
            status="idle",
            cwd="/Users/kangmo/sacle/src/blink",
        )
    )
    existing = state.create_binding(
        binding=service_binding(
            codex_thread_id="thread-1",
            message_thread_id=91,
        )
    )
    service = GatewayService(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )

    bindings = service.link_loaded_threads()

    assert bindings == [existing]


def test_link_current_thread_marks_existing_events_seen() -> None:
    config = GatewayConfig(
        telegram_bot_token="token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )
    state = DummyState()
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Remove browser entitlement",
            status="idle",
            cwd="/Users/kangmo/sacle/src/blink",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="Existing message.",
        )
    )
    service = GatewayService(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )

    service.link_current_thread()

    assert state.has_seen_event("thread-1", "thread-1:turn-1:item-1") is True


def test_link_current_thread_reuses_mapping_after_thread_title_change() -> None:
    config = GatewayConfig(
        telegram_bot_token="token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )
    state = DummyState()
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="original-title",
            status="idle",
            cwd="/Users/kangmo/sacle/src/blink",
        )
    )
    existing = state.create_binding(
        service_binding(
            codex_thread_id="thread-1",
            message_thread_id=91,
            topic_name="old-topic-title",
        )
    )
    codex.set_thread_title("thread-1", "new-thread-title")
    service = GatewayService(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )

    binding = service.link_current_thread()

    assert binding == existing
    assert telegram._next_topic_id == 1


def test_bind_topic_to_project_defaults_to_untitled() -> None:
    config = GatewayConfig(
        telegram_bot_token="token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )
    state = DummyState()
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="existing-thread",
            status="idle",
            cwd="/Users/kangmo/sacle/src/blink",
        )
    )
    service = GatewayService(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )

    binding = service.bind_topic_to_project(
        chat_id=-100100,
        message_thread_id=55,
        project_id="/Users/kangmo/sacle/src/blink",
    )

    assert codex.created_threads == [
        CodexThread(
            thread_id="thread-2",
            title="untitled",
            status="idle",
            cwd="/Users/kangmo/sacle/src/blink",
        )
    ]
    assert telegram.edited_topics == [(-100100, 55, "(blink) untitled")]
    assert binding.topic_name == "(blink) untitled"


def test_recreate_topic_creates_new_topic_and_replays_latest_assistant_block() -> None:
    config = GatewayConfig(
        telegram_bot_token="token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )
    state = DummyState()
    existing = state.create_binding(
        service_binding(
            codex_thread_id="thread-1",
            message_thread_id=55,
            topic_name="(blink) existing",
        )
    )
    state.mark_event_seen("thread-1", "event-1")
    state.mark_event_seen("thread-1", "event-2")
    state.upsert_outbound_message(
        OutboundMessage(
            codex_thread_id="thread-1",
            event_id="event-2",
            telegram_message_ids=(10,),
            text="latest reply",
        )
    )
    telegram = DummyTelegramClient()
    telegram.dead_topics.add((existing.chat_id, existing.message_thread_id))
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Recover topic",
            status="idle",
            cwd="/Users/kangmo/sacle/src/blink",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="event-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="older reply",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="event-2",
            thread_id="thread-1",
            kind="assistant_message",
            text="latest reply",
        )
    )
    service = GatewayService(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )

    recreated = service.recreate_topic("thread-1")

    assert recreated.message_thread_id == 1
    assert recreated.topic_name == "(blink) Recover topic"
    assert telegram.created_topics == [(-100100, "(blink) Recover topic")]
    assert state.get_binding_by_thread("thread-1") == recreated
    assert state.get_outbound_message("thread-1", "event-2") is None
    assert state.has_seen_event("thread-1", "event-1") is True
    assert state.has_seen_event("thread-1", "event-2") is False


def service_binding(
    *,
    codex_thread_id: str,
    message_thread_id: int,
    topic_name: str = "(blink) Remove browser entitlement",
):
    return __import__("codex_telegram_gateway.models", fromlist=["Binding"]).Binding(
        codex_thread_id=codex_thread_id,
        chat_id=-100100,
        message_thread_id=message_thread_id,
        topic_name=topic_name,
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/blink",
    )
