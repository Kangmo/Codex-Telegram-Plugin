from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.daemon import GatewayDaemon, _parse_topic_name
from codex_telegram_gateway.history_command import CALLBACK_HISTORY_PREFIX
from pathlib import Path
from codex_telegram_gateway.telegram_api import TelegramRetryAfterError

from codex_telegram_gateway.models import (
    ACTIVE_BINDING_STATUS,
    Binding,
    CLOSED_BINDING_STATUS,
    CodexEvent,
    CodexHistoryEntry,
    CodexThread,
    DELETED_BINDING_STATUS,
    HistoryViewState,
    InboundMessage,
    PendingTurn,
    StartedTurn,
    TopicCreationJob,
    TopicLifecycle,
    TopicHistoryEntry,
    TopicProject,
    TurnResult,
)

from tests.unit.support import DummyCodexBridge, DummyState, DummyTelegramClient


def make_binding(*, binding_status: str = ACTIVE_BINDING_STATUS) -> Binding:
    return Binding(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        topic_name="(gateway-project) thread-1",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
        binding_status=binding_status,
    )


def make_config() -> GatewayConfig:
    return GatewayConfig(
        telegram_bot_token="token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )


def test_sync_codex_once_emits_only_unseen_events() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="Completed the refactor.",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()
    daemon.sync_codex_once()

    assert telegram.sent_messages == [(-100100, 77, "Completed the refactor.", None)]
    assert state.list_projects() == [
        __import__("codex_telegram_gateway.models", fromlist=["CodexProject"]).CodexProject(
            project_id="/Users/kangmo/sacle/src/gateway-project",
            project_name="gateway-project",
        )
    ]


def test_sync_codex_once_edits_existing_message_when_same_event_grows() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="I found the first issue.",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()
    codex.replace_event("thread-1", "thread-1:turn-1:item-1", "I found the first issue.\nAnd the second one.")
    daemon.sync_codex_once()

    assert telegram.sent_messages == [(-100100, 77, "I found the first issue.", None)]
    assert telegram.edited_messages == [
        (-100100, 1, "I found the first issue.\nAnd the second one.", None),
    ]


def test_poll_telegram_once_marks_binding_closed_and_reopened_from_topic_events() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_topic_lifecycle(
        TopicLifecycle(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            completed_at=10.0,
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    telegram.push_topic_closed_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=999,
    )
    daemon.poll_telegram_once()
    assert state.get_binding_by_thread("thread-1").binding_status == CLOSED_BINDING_STATUS

    telegram.push_topic_reopened_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=999,
    )
    daemon.poll_telegram_once()

    assert state.get_binding_by_thread("thread-1").binding_status == ACTIVE_BINDING_STATUS
    assert state.get_topic_lifecycle("thread-1").completed_at is None


def test_poll_telegram_once_topic_rename_updates_codex_thread_title_for_authorized_user() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="(gateway-project) renamed from telegram",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert codex.renamed_threads == [("thread-1", "renamed from telegram")]
    assert state.get_binding_by_thread("thread-1").topic_name == "(gateway-project) renamed from telegram"
    assert telegram.edited_topics == []


def test_poll_telegram_once_topic_rename_restores_canonical_name_when_prefix_changes() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="(wrong-project) renamed from telegram",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert codex.renamed_threads == []
    assert telegram.edited_topics == [(-100100, 77, "(gateway-project) thread-1")]


def test_poll_telegram_once_topic_rename_ignores_echo_for_stored_name() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="(gateway-project) thread-1",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert codex.renamed_threads == []
    assert telegram.edited_topics == []


def test_poll_telegram_once_topic_rename_ignores_missing_binding() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="(gateway-project) renamed from telegram",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert codex.renamed_threads == []
    assert telegram.edited_topics == []


def test_poll_telegram_once_topic_rename_accepts_canonical_name_without_extra_work() -> None:
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) stale-local-name",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="(gateway-project) thread-1",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert codex.renamed_threads == []
    assert state.get_binding_by_thread("thread-1").topic_name == "(gateway-project) thread-1"
    assert telegram.edited_topics == []


def test_poll_telegram_once_topic_rename_marks_binding_deleted_when_normalized_edit_hits_missing_topic() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="(gateway-project)   rename me   ",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )

    def fail_edit_forum_topic(chat_id: int, message_thread_id: int, name: str) -> None:
        del chat_id, message_thread_id, name
        raise RuntimeError("Topic closed")

    telegram.edit_forum_topic = fail_edit_forum_topic
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert codex.renamed_threads == [("thread-1", "rename me")]
    assert state.get_binding_by_thread("thread-1").binding_status == DELETED_BINDING_STATUS


def test_poll_telegram_once_topic_rename_swallows_unexpected_error_when_normalizing_topic() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="(gateway-project)   rename me   ",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )

    def fail_edit_forum_topic(chat_id: int, message_thread_id: int, name: str) -> None:
        del chat_id, message_thread_id, name
        raise RuntimeError("boom")

    telegram.edit_forum_topic = fail_edit_forum_topic
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert codex.renamed_threads == [("thread-1", "rename me")]
    assert state.get_binding_by_thread("thread-1").topic_name == "(gateway-project) rename me"
    assert state.get_telegram_cursor() == 2


def test_poll_telegram_once_topic_rename_reconciles_normalized_title_back_to_telegram() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="(gateway-project)   rename me   ",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )

    def rename_thread(thread_id: str, thread_name: str) -> CodexThread:
        codex.renamed_threads.append((thread_id, thread_name))
        codex.set_thread_title(thread_id, "rename me")
        return codex.read_thread(thread_id)

    codex.rename_thread = rename_thread
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert telegram.edited_topics == [(-100100, 77, "(gateway-project) rename me")]


def test_poll_telegram_once_topic_rename_marks_binding_deleted_when_restore_hits_missing_topic() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="(wrong-project) renamed from telegram",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )

    def fail_edit_forum_topic(chat_id: int, message_thread_id: int, name: str) -> None:
        del chat_id, message_thread_id, name
        raise RuntimeError("thread not found")

    telegram.edit_forum_topic = fail_edit_forum_topic
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.get_binding_by_thread("thread-1").binding_status == DELETED_BINDING_STATUS


def test_poll_telegram_once_topic_rename_swallows_unexpected_error_when_restoring_canonical_name() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="(wrong-project) renamed from telegram",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )

    def fail_edit_forum_topic(chat_id: int, message_thread_id: int, name: str) -> None:
        del chat_id, message_thread_id, name
        raise RuntimeError("boom")

    telegram.edit_forum_topic = fail_edit_forum_topic
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.get_binding_by_thread("thread-1").binding_status == ACTIVE_BINDING_STATUS
    assert state.get_telegram_cursor() == 2


def test_parse_topic_name_accepts_valid_names_and_rejects_invalid_or_empty_values() -> None:
    assert _parse_topic_name("(project) thread") == ("project", "thread")
    assert _parse_topic_name("no prefix") is None
    assert _parse_topic_name("(project)   ") is None


def test_sync_codex_once_prefixes_running_topic_status() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-1",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="in_progress")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert telegram.edited_topics == [(-100100, 77, "🟢 (gateway-project) thread-1")]
    assert state.get_binding_by_thread("thread-1").topic_name == "🟢 (gateway-project) thread-1"


def test_sync_codex_once_prefixes_waiting_approval_topic_status() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-1",
            waiting_for_approval=True,
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(
        turn_id="turn-1",
        status="interrupted",
        waiting_for_approval=True,
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert telegram.edited_topics == [(-100100, 77, "🟠 (gateway-project) thread-1")]


def test_sync_codex_once_prefixes_failed_topic_status_and_keeps_it_after_pending_turn_clears() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-1",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="failed")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()
    telegram.edited_topics.clear()
    daemon.sync_codex_once()

    assert state.get_pending_turn("thread-1") is None
    assert state.get_binding_by_thread("thread-1").topic_name == "💥 (gateway-project) thread-1"
    assert telegram.edited_topics == []


def test_sync_codex_once_prefixes_closed_binding_topic_status() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert telegram.edited_topics == [(-100100, 77, "⚫ (gateway-project) thread-1")]


def test_sync_codex_once_disables_topic_status_prefixes_after_permission_error() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-1",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="in_progress")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )
    edit_attempts = 0

    def fail_edit_forum_topic(chat_id: int, message_thread_id: int, name: str) -> None:
        nonlocal edit_attempts
        del chat_id, message_thread_id, name
        edit_attempts += 1
        raise RuntimeError("Not enough rights to manage topics")

    telegram.edit_forum_topic = fail_edit_forum_topic

    daemon.sync_codex_once()
    daemon.sync_codex_once()

    assert edit_attempts == 1
    assert state.get_binding_by_thread("thread-1").topic_name == "(gateway-project) thread-1"


def test_poll_telegram_once_topic_rename_strips_status_prefix_before_updating_codex() -> None:
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="🟢 (gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-1",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_topic_edited_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        topic_name="🟢 (gateway-project) renamed from telegram",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="in_progress")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert codex.renamed_threads == [("thread-1", "renamed from telegram")]
    assert state.get_binding_by_thread("thread-1").topic_name == "🟢 (gateway-project) renamed from telegram"


def test_sync_codex_once_skips_outbound_for_closed_binding_and_clears_terminal_pending_turn() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-10",
            waiting_for_approval=False,
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.inspect_results[("thread-1", "turn-10")] = TurnResult(
        turn_id="turn-10",
        status="completed",
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-10:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="Hidden while topic is closed.",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert telegram.sent_messages == []
    assert state.get_pending_turn("thread-1") is None
    assert state.has_seen_event("thread-1", "thread-1:turn-10:item-1") is False


def test_sync_codex_once_marks_binding_deleted_when_topic_rename_hits_missing_topic() -> None:
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) stale-title",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="fresh-title",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    def fail_edit_forum_topic(chat_id: int, message_thread_id: int, name: str) -> None:
        del chat_id, message_thread_id, name
        raise RuntimeError("Topic closed")

    telegram.edit_forum_topic = fail_edit_forum_topic

    daemon.sync_codex_once()

    assert state.get_binding_by_thread("thread-1").binding_status == DELETED_BINDING_STATUS
    assert telegram.sent_messages == []


def test_deliver_inbound_once_waits_for_closed_binding_to_reopen() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    queued_message = InboundMessage(
        telegram_update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        codex_thread_id="thread-1",
        text="queued until reopen",
    )
    state.enqueue_inbound(queued_message)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.deliver_inbound_once()

    assert codex.started_turns == []
    assert state.list_pending_inbound() == [queued_message]

    state.create_binding(make_binding(binding_status=ACTIVE_BINDING_STATUS))

    daemon.deliver_inbound_once()

    assert codex.started_turns == [
        StartedTurn(
            thread_id="thread-1",
            text="queued until reopen",
        )
    ]


def test_poll_telegram_once_ignores_messages_for_closed_binding() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="do not route while closed",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.list_pending_inbound() == []


def test_sync_codex_once_attaches_response_widget_with_recent_history() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.record_topic_history(-100100, 77, text="go ahead implement it")
    state.record_topic_history(-100100, 77, text="i created a new project")
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="Completed the gateway update.",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert telegram.edited_reply_markups == [
        (
            -100100,
            1,
            {
                "inline_keyboard": [
                        [{"text": "✓ Ready", "callback_data": "gw:resp:noop"}],
                        [
                            {"text": "↑ i created a new pro…", "callback_data": "gw:resp:recall:0"},
                            {"text": "↑ go ahead implement…", "callback_data": "gw:resp:recall:1"},
                        ],
                    [
                        {"text": "↺ New", "callback_data": "gw:resp:new"},
                        {"text": "📁 Project", "callback_data": "gw:resp:project"},
                        {"text": "📍 Status", "callback_data": "gw:resp:status"},
                        {"text": "🔄 Sync", "callback_data": "gw:resp:sync"},
                    ],
                ]
            },
        )
    ]


def test_sync_codex_once_updates_response_widget_from_running_to_ready() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-1",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="Working on it.",
        )
    )
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="in_progress")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="completed")
    daemon.sync_codex_once()

    assert telegram.edited_reply_markups == [
        (
            -100100,
            1,
            {"inline_keyboard": [[{"text": "⏳ Working", "callback_data": "gw:resp:noop"}]]},
        ),
        (
            -100100,
            1,
            {
                "inline_keyboard": [
                    [{"text": "✓ Ready", "callback_data": "gw:resp:noop"}],
                    [
                        {"text": "↺ New", "callback_data": "gw:resp:new"},
                        {"text": "📁 Project", "callback_data": "gw:resp:project"},
                        {"text": "📍 Status", "callback_data": "gw:resp:status"},
                        {"text": "🔄 Sync", "callback_data": "gw:resp:sync"},
                    ],
                ]
            },
        ),
    ]


def test_sync_codex_once_links_newly_loaded_codex_app_threads() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.create_thread("/Users/kangmo/sacle/src/other-project", "fresh thread")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    linked = state.get_binding_by_thread("thread-2")
    assert linked.topic_name == "(other-project) fresh thread"
    assert telegram.created_topics == [(-100100, "(other-project) fresh thread")]
    assert codex.ensured_projects == [
        "/Users/kangmo/sacle/src/other-project",
        "/Users/kangmo/sacle/src/gateway-project",
    ]


def test_sync_codex_once_pushes_telegram_known_project_back_into_codex_sidebar_state() -> None:
    state = DummyState()
    state.upsert_project(
        __import__("codex_telegram_gateway.models", fromlist=["CodexProject"]).CodexProject(
            project_id="/Users/kangmo/sacle/src/sacle-deposit-final",
            project_name="sacle-deposit-final",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert codex.ensured_projects == [
        "/Users/kangmo/sacle/src/gateway-project",
        "/Users/kangmo/sacle/src/sacle-deposit-final",
    ]


def test_poll_telegram_once_queues_only_authorized_updates() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=999,
        text="Ignore me.",
    )
    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="Please continue.",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    pending = state.list_pending_inbound()
    assert pending == [
        InboundMessage(
            telegram_update_id=2,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Please continue.",
        )
    ]


def test_poll_telegram_once_handles_commands_without_queueing_to_codex() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway help",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.list_pending_inbound() == []
    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "Available gateway commands:\n"
            "/gateway <subcommand> - Run a gateway control action\n\n"
            "Gateway subcommands:\n"
            "/gateway doctor - Show Telegram and Codex App gateway status\n"
            "/gateway projects - List loaded Codex App projects\n"
            "/gateway threads - List loaded Codex App threads\n"
            "/gateway history - Show paginated history for this Codex thread\n"
            "/gateway bindings - List Codex thread to Telegram topic bindings\n"
            "/gateway create_thread - Create a new Codex thread in this topic\n"
            "/gateway project - Choose or switch the Codex project for this topic\n"
            "/gateway status - Show the current topic binding and thread status\n"
            "/gateway sync - Audit bindings and recover deleted topics\n"
            "/gateway help - Show available gateway commands\n\n"
            "Compatibility aliases inside `/gateway`: new, start, sessions, commands\n"
            "All other slash commands are passed through to the bound Codex thread unchanged.",
            None,
        )
    ]


def test_poll_telegram_once_gateway_history_renders_latest_page_and_persists_view() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway history",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.set_history_entries(
        "thread-1",
        [
            CodexHistoryEntry(
                entry_id=f"entry-{index}",
                kind="user" if index % 2 == 0 else "assistant",
                text=f"history entry {index} " + ("x" * 500),
                timestamp="2026-04-15T10:00:00Z",
            )
            for index in range(10)
        ],
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    sent_text = telegram.sent_messages[0][2]
    sent_markup = telegram.sent_messages[0][3]
    assert sent_text.startswith("📋 [(gateway-project) thread-1] Messages (10 total)")
    assert sent_markup == {
        "inline_keyboard": [
            [
                {"text": "◀ Older", "callback_data": f"{CALLBACK_HISTORY_PREFIX}0:thread-1"},
                {"text": "2/2", "callback_data": "tp:noop"},
            ]
        ]
    }
    assert state.get_history_view(-100100, 77) == HistoryViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        codex_thread_id="thread-1",
        page_index=1,
    )


def test_poll_telegram_once_history_callback_pages_existing_view() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_history_view(
        HistoryViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=42,
            codex_thread_id="thread-1",
            page_index=1,
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-history",
        chat_id=-100100,
        message_thread_id=77,
        message_id=42,
        from_user_id=111,
        data=f"{CALLBACK_HISTORY_PREFIX}0:thread-1",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.set_history_entries(
        "thread-1",
        [
            CodexHistoryEntry(
                entry_id=f"entry-{index}",
                kind="assistant",
                text=f"history entry {index} " + ("x" * 500),
                timestamp="2026-04-15T10:00:00Z",
            )
            for index in range(10)
        ],
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert telegram.edited_messages == [
        (
            -100100,
            42,
            telegram.edited_messages[0][2],
            {
                "inline_keyboard": [
                    [
                        {"text": "1/2", "callback_data": "tp:noop"},
                        {"text": "Newer ▶", "callback_data": f"{CALLBACK_HISTORY_PREFIX}1:thread-1"},
                    ]
                ]
            },
        )
    ]
    assert state.get_history_view(-100100, 77) == HistoryViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=42,
        codex_thread_id="thread-1",
        page_index=0,
    )
    assert telegram.answered_callback_queries == [("cb-history", "Page updated.")]


def test_poll_telegram_once_history_callback_rejects_stale_message() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_history_view(
        HistoryViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=41,
            codex_thread_id="thread-1",
            page_index=0,
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-history-stale",
        chat_id=-100100,
        message_thread_id=77,
        message_id=42,
        from_user_id=111,
        data=f"{CALLBACK_HISTORY_PREFIX}0:thread-1",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert telegram.edited_messages == []
    assert telegram.answered_callback_queries == [("cb-history-stale", "This history view is stale.")]


def test_poll_telegram_once_requeues_recent_message_from_response_widget() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.record_topic_history(
        -100100,
        77,
        text="please check the screenshot",
        local_image_paths=("/tmp/example-image.png",),
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=5,
        callback_query_id="cb-recall",
        chat_id=-100100,
        message_thread_id=77,
        message_id=42,
        from_user_id=111,
        data="gw:resp:recall:0",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.list_pending_inbound() == [
        InboundMessage(
            telegram_update_id=5,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="please check the screenshot",
            local_image_paths=("/tmp/example-image.png",),
        )
    ]
    assert telegram.answered_callback_queries == [("cb-recall", "Queued.")]


def test_poll_telegram_once_gateway_create_thread_rebinds_bound_topic() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway create_thread",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    rebound = state.get_binding_by_topic(-100100, 77)
    assert rebound.codex_thread_id == "thread-2"
    assert rebound.topic_name == "(gateway-project) untitled"
    assert codex.created_threads == [
        CodexThread(
            thread_id="thread-2",
            title="untitled",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    ]
    assert telegram.edited_topics == [(-100100, 77, "(gateway-project) untitled")]
    assert state.list_pending_inbound() == []


def test_poll_telegram_once_gateway_project_opens_picker_for_bound_topic() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway project",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    topic_project = state.get_topic_project(-100100, 77)
    assert topic_project == TopicProject(
        chat_id=-100100,
        message_thread_id=77,
        topic_name="(gateway-project) thread-1",
        project_id=None,
        picker_message_id=1,
        pending_update_id=None,
        pending_user_id=None,
        pending_text=None,
    )
    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "Select Codex Project\n\n"
            "Topic: (gateway-project) thread-1\n\n"
            "Choose an existing loaded Codex App project below, or browse folders from your Mac home directory.\n\n"
            "First message:\n"
            "(empty message)",
            {
                "inline_keyboard": [
                    [{"text": "📁 gateway-project", "callback_data": "tp:prj:0"}],
                    [{"text": "📂 Browse Home Folder", "callback_data": "tp:browse:open"}],
                    [{"text": "Cancel", "callback_data": "tp:cancel"}],
                ]
            },
        )
    ]


def test_poll_telegram_once_gateway_bindings_shows_dashboard_and_sessions_alias_refreshes() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway bindings",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "Gateway bindings\n\n"
            "🟢 (gateway-project) thread-1\n"
            "topic `77` • thread `thread-1` • status `active`\n\n"
            "Use `/gateway sync` to audit bindings and recover deleted topics.",
            {
                "inline_keyboard": [
                    [
                        {"text": "Refresh", "callback_data": "gw:sessions:refresh"},
                        {"text": "Dismiss", "callback_data": "gw:sessions:dismiss"},
                    ]
                ]
            },
        )
    ]

    codex.set_thread_title("thread-1", "renamed thread")
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-sessions",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:refresh",
    )

    daemon.poll_telegram_once()

    assert telegram.edited_messages[-1] == (
        -100100,
        1,
        "Gateway bindings\n\n"
        "🟢 (gateway-project) renamed thread\n"
        "topic `77` • thread `thread-1` • status `active`\n\n"
        "Use `/gateway sync` to audit bindings and recover deleted topics.",
        {
            "inline_keyboard": [
                [
                    {"text": "Refresh", "callback_data": "gw:sessions:refresh"},
                    {"text": "Dismiss", "callback_data": "gw:sessions:dismiss"},
                ]
            ]
        },
    )
    assert telegram.answered_callback_queries[-1] == ("cb-sessions", "Refreshed.")


def test_poll_telegram_once_aligned_command_names_show_codex_app_summaries() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway doctor",
    )
    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway projects",
    )
    telegram.push_update(
        update_id=3,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway threads",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "Gateway doctor\n\n"
            "Chat: `dummy-chat` (supergroup)\n"
            "Loaded projects: `1`\n"
            "Loaded threads: `1`\n"
            "Current topic binding: `thread-1`",
            None,
        ),
        (
            -100100,
            77,
            "Loaded Codex App projects\n\n"
            "- `gateway-project`\n"
            "  `/Users/kangmo/sacle/src/gateway-project`",
            None,
        ),
        (
            -100100,
            77,
            "Loaded Codex App threads\n\n"
            "- `(gateway-project) thread-1`\n"
            "  status `idle` • id `thread-1`",
            None,
        ),
    ]


def test_poll_telegram_once_gateway_sync_audits_and_fix_recovers_dead_topic() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.dead_topics.add((-100100, 77))
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway sync",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="event-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="latest reply",
        )
    )
    state.mark_event_seen("thread-1", "event-1")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.get_binding_by_thread("thread-1").binding_status == DELETED_BINDING_STATUS
    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "Gateway sync\n\n"
            "Loaded Codex App threads: 1\n"
            "Bound Telegram topics: 1\n"
            "✓ All loaded threads have Telegram topics\n"
            "⚠ 1 bound topic(s) were deleted in Telegram",
            {
                "inline_keyboard": [
                    [
                        {"text": "🔧 Fix 1", "callback_data": "gw:sync:fix"},
                        {"text": "Dismiss", "callback_data": "gw:sync:dismiss"},
                    ]
                ]
            },
        )
    ]

    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-sync",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sync:fix",
    )

    daemon.poll_telegram_once()

    rebound = state.get_binding_by_thread("thread-1")
    assert rebound.message_thread_id == 1
    assert rebound.binding_status == ACTIVE_BINDING_STATUS
    assert telegram.created_topics == [(-100100, "(gateway-project) thread-1")]
    assert telegram.edited_messages[-1] == (
        -100100,
        1,
        "Fixed 1 issue(s).\n\n"
        "Loaded Codex App threads: 1\n"
        "Bound Telegram topics: 1\n"
        "✓ All loaded threads have Telegram topics\n"
        "✓ All bound Telegram topics are reachable\n\n"
        "No fixes needed.",
        None,
    )
    assert telegram.answered_callback_queries[-1] == ("cb-sync", "Fixed 1 issue(s).")


def test_poll_telegram_once_passthroughs_non_gateway_slash_commands_to_codex() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/doctor",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert telegram.sent_messages == []
    assert state.list_pending_inbound() == [
        InboundMessage(
            telegram_update_id=1,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="/doctor",
        )
    ]


def test_poll_telegram_once_queues_photo_message_for_bound_topic(tmp_path) -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    photo_path = tmp_path / "telegram-photo.jpg"
    photo_path.write_bytes(b"image-bytes")
    telegram._updates.append(
        {
            "kind": "message",
            "update_id": 3,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 111,
            "text": "Please inspect the attachment.",
            "local_image_paths": (str(photo_path),),
        }
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.list_pending_inbound() == [
        InboundMessage(
            telegram_update_id=3,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Please inspect the attachment.",
            local_image_paths=(str(photo_path),),
        )
    ]


def test_poll_telegram_once_queues_message_during_active_turn_and_sends_steer_widget() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-9",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=9,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="Please add queue metrics.",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="running",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.list_pending_inbound() == [
        InboundMessage(
            telegram_update_id=9,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Please add queue metrics.",
        )
    ]
    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "Queued while Codex is still answering. This will run after the current answer finishes.\n\n"
            "Queued message:\n"
            "Please add queue metrics.",
            {
                "inline_keyboard": [[{"text": "Steer", "callback_data": "gw:queue:steer:9"}]]
            },
        )
    ]


def test_poll_telegram_once_steers_queued_message_into_active_turn() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-9",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=9,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="Please add queue metrics.",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="running",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()
    telegram.push_callback_query(
        update_id=10,
        callback_query_id="cb-steer",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:queue:steer:9",
    )

    daemon.poll_telegram_once()

    assert codex.steered_turns == [
        (
            "turn-9",
            StartedTurn(thread_id="thread-1", text="Please add queue metrics."),
        )
    ]
    assert state.pending_inbound_count() == 0
    assert telegram.edited_reply_markups[-1] == (-100100, 1, None)
    assert telegram.answered_callback_queries[-1] == ("cb-steer", "Steered.")
    assert telegram.sent_chat_actions[-1] == (-100100, 77, "typing")


def test_deliver_inbound_once_submits_first_message_to_idle_thread() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    state.enqueue_inbound(
        InboundMessage(
            telegram_update_id=2,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Please continue.",
        )
    )

    daemon.deliver_inbound_once()

    assert codex.started_turns == [
        StartedTurn(thread_id="thread-1", text="Please continue."),
    ]
    assert telegram.sent_chat_actions == [(-100100, 77, "typing")]
    assert state.pending_inbound_count() == 0
    assert state.get_pending_turn("thread-1") == PendingTurn(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        turn_id="turn-1",
        waiting_for_approval=False,
    )


def test_deliver_inbound_once_submits_message_to_not_loaded_thread() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="notLoaded",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    state.enqueue_inbound(
        InboundMessage(
            telegram_update_id=3,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Resume from Telegram.",
        )
    )

    daemon.deliver_inbound_once()

    assert codex.started_turns == [
        StartedTurn(thread_id="thread-1", text="Resume from Telegram."),
    ]
    assert telegram.sent_chat_actions == [(-100100, 77, "typing")]
    assert state.pending_inbound_count() == 0
    assert state.get_pending_turn("thread-1") is not None


def test_deliver_inbound_once_submits_message_with_local_image() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    state.enqueue_inbound(
        InboundMessage(
            telegram_update_id=4,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Please inspect the screenshot.",
            local_image_paths=("/tmp/example-image.png",),
        )
    )

    daemon.deliver_inbound_once()

    assert codex.started_turns == [
        StartedTurn(
            thread_id="thread-1",
            text="Please inspect the screenshot.",
            local_image_paths=("/tmp/example-image.png",),
        ),
    ]
    assert telegram.sent_chat_actions == [(-100100, 77, "typing")]
    assert state.pending_inbound_count() == 0
    assert state.get_pending_turn("thread-1") is not None


def test_sync_codex_once_reports_interrupted_turn_to_telegram() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.next_turn_result = TurnResult(turn_id="turn-9", status="interrupted")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    state.enqueue_inbound(
        InboundMessage(
            telegram_update_id=5,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Please continue.",
        )
    )

    daemon.deliver_inbound_once()
    daemon.sync_codex_once()

    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "Codex started processing your message, but the turn was interrupted before a final answer was produced.",
            None,
        )
    ]
    assert state.pending_inbound_count() == 0
    assert state.get_pending_turn("thread-1") is None


def test_deliver_inbound_once_keeps_typing_pending_for_approval_blocked_turn() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.next_turn_result = TurnResult(
        turn_id="turn-10",
        status="interrupted",
        waiting_for_approval=True,
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    state.enqueue_inbound(
        InboundMessage(
            telegram_update_id=6,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Query the local database.",
        )
    )

    daemon.deliver_inbound_once()

    assert state.get_pending_turn("thread-1") == PendingTurn(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        turn_id="turn-10",
        waiting_for_approval=True,
    )
    assert telegram.sent_messages == []
    assert telegram.sent_chat_actions == [(-100100, 77, "typing")]
    assert state.pending_inbound_count() == 0


def test_sync_codex_once_continues_typing_for_approval_blocked_turn() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-10",
            waiting_for_approval=True,
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.inspect_results[("thread-1", "turn-10")] = TurnResult(
        turn_id="turn-10",
        status="interrupted",
        waiting_for_approval=True,
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert telegram.sent_chat_actions == [(-100100, 77, "typing")]
    assert state.get_pending_turn("thread-1") is not None


def test_sync_codex_once_clears_pending_turn_after_matching_reply() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-10",
            waiting_for_approval=True,
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.inspect_results[("thread-1", "turn-10")] = TurnResult(
        turn_id="turn-10",
        status="completed",
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-10:item-2",
            thread_id="thread-1",
            kind="assistant_message",
            text="The query needs approval first.",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert telegram.sent_messages == [
        (-100100, 77, "The query needs approval first.", None),
    ]
    assert state.get_pending_turn("thread-1") is None


def test_poll_telegram_once_shows_project_picker_for_first_unbound_topic_message() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_topic_created_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=88,
        from_user_id=111,
        topic_name="lingodb",
    )
    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=88,
        from_user_id=111,
        text="hi",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    topic_project = state.get_topic_project(-100100, 88)
    assert topic_project == TopicProject(
        chat_id=-100100,
        message_thread_id=88,
        topic_name="lingodb",
        project_id=None,
        picker_message_id=1,
        pending_update_id=2,
        pending_user_id=111,
        pending_text="hi",
    )
    assert telegram.sent_messages == [
        (
            -100100,
            88,
            "Select Codex Project\n\n"
            "Topic: lingodb\n\n"
            "Choose an existing loaded Codex App project below, or browse folders from your Mac home directory.\n\n"
            "First message:\n"
            "hi",
            {
                "inline_keyboard": [
                    [{"text": "📁 gateway-project", "callback_data": "tp:prj:0"}],
                    [{"text": "📂 Browse Home Folder", "callback_data": "tp:browse:open"}],
                    [{"text": "Cancel", "callback_data": "tp:cancel"}],
                ]
            },
        )
    ]
    assert state.pending_inbound_count() == 0


def test_poll_telegram_once_binds_topic_after_project_selection() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_topic_created_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=88,
        from_user_id=111,
        topic_name="lingodb",
    )
    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=88,
        from_user_id=111,
        text="hi",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()
    telegram.push_callback_query(
        update_id=3,
        callback_query_id="cb-1",
        chat_id=-100100,
        message_thread_id=88,
        message_id=1,
        from_user_id=111,
        data="tp:prj:0",
    )

    daemon.poll_telegram_once()

    binding = state.get_binding_by_topic(-100100, 88)
    assert binding.codex_thread_id == "thread-2"
    assert binding.project_id == "/Users/kangmo/sacle/src/gateway-project"
    assert binding.topic_name == "(gateway-project) untitled"
    assert codex.created_threads == [
        CodexThread(
            thread_id="thread-2",
            title="untitled",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    ]
    assert telegram.edited_topics == [(-100100, 88, "(gateway-project) untitled")]
    assert telegram.edited_reply_markups == [(-100100, 1, None)]
    assert telegram.answered_callback_queries == [("cb-1", "Selected gateway-project.")]
    assert state.list_pending_inbound() == [
        InboundMessage(
            telegram_update_id=2,
            chat_id=-100100,
            message_thread_id=88,
            from_user_id=111,
            codex_thread_id="thread-2",
            text="hi",
        )
    ]
    assert state.get_topic_project(-100100, 88) is None


def test_poll_telegram_once_browses_home_folder_and_binds_selected_directory(
    tmp_path: Path,
    monkeypatch,
) -> None:
    home_path = tmp_path / "home"
    home_path.mkdir()
    project_a = home_path / "project-a"
    project_b = home_path / "project-b"
    project_a.mkdir()
    project_b.mkdir()
    monkeypatch.setattr("codex_telegram_gateway.daemon._browser_home_path", lambda: home_path)

    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_topic_created_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=91,
        from_user_id=111,
        topic_name="new feature",
    )
    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=91,
        from_user_id=111,
        text="please investigate",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()
    telegram.push_callback_query(
        update_id=3,
        callback_query_id="cb-open",
        chat_id=-100100,
        message_thread_id=91,
        message_id=1,
        from_user_id=111,
        data="tp:browse:open",
    )
    telegram.push_callback_query(
        update_id=4,
        callback_query_id="cb-enter",
        chat_id=-100100,
        message_thread_id=91,
        message_id=1,
        from_user_id=111,
        data="tp:browse:enter:0",
    )
    telegram.push_callback_query(
        update_id=5,
        callback_query_id="cb-select",
        chat_id=-100100,
        message_thread_id=91,
        message_id=1,
        from_user_id=111,
        data="tp:browse:select",
    )

    daemon.poll_telegram_once()
    daemon.poll_telegram_once()
    daemon.poll_telegram_once()

    binding = state.get_binding_by_topic(-100100, 91)
    assert binding.codex_thread_id == "thread-2"
    assert binding.project_id == str(project_a.resolve())
    assert binding.topic_name == "(project-a) untitled"
    assert state.get_project(str(project_a.resolve())).project_name == "project-a"
    assert telegram.edited_messages[:2] == [
        (
            -100100,
            1,
            "Select Working Directory\n\n"
            "Current: ~\n\n"
            "Tap a folder to enter, or select current directory.",
            {
                "inline_keyboard": [
                    [
                        {"text": "📁 project-a", "callback_data": "tp:browse:enter:0"},
                        {"text": "📁 project-b", "callback_data": "tp:browse:enter:1"},
                    ],
                    [
                        {"text": "..", "callback_data": "tp:browse:up"},
                        {"text": "🏠", "callback_data": "tp:browse:home"},
                        {"text": "Select", "callback_data": "tp:browse:select"},
                    ],
                    [
                        {"text": "← Projects", "callback_data": "tp:browse:back"},
                        {"text": "Cancel", "callback_data": "tp:cancel"},
                    ],
                ]
            },
        ),
        (
            -100100,
            1,
            "Select Working Directory\n\n"
            "Current: ~/project-a\n\n"
            "Tap a folder to enter, or select current directory.",
            {
                "inline_keyboard": [
                    [
                        {"text": "..", "callback_data": "tp:browse:up"},
                        {"text": "🏠", "callback_data": "tp:browse:home"},
                        {"text": "Select", "callback_data": "tp:browse:select"},
                    ],
                    [
                        {"text": "← Projects", "callback_data": "tp:browse:back"},
                        {"text": "Cancel", "callback_data": "tp:cancel"},
                    ],
                ]
            },
        ),
    ]
    assert state.list_pending_inbound() == [
        InboundMessage(
            telegram_update_id=2,
            chat_id=-100100,
            message_thread_id=91,
            from_user_id=111,
            codex_thread_id="thread-2",
            text="please investigate",
        )
    ]


def test_sync_codex_once_renames_topic_when_codex_thread_title_changes() -> None:
    state = DummyState()
    binding = state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) untitled",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="untitled",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    codex.set_thread_title("thread-1", "actual thread title")
    daemon.sync_codex_once()

    assert telegram.edited_topics == [(-100100, 77, "(gateway-project) actual thread title")]
    assert state.get_binding_by_thread(binding.codex_thread_id).topic_name == "(gateway-project) actual thread title"


def test_poll_telegram_once_backfills_topic_lifecycle_for_existing_binding_without_row() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="Please continue.",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    lifecycle = state.get_topic_lifecycle("thread-1")
    assert lifecycle is not None
    assert lifecycle.bound_at is not None
    assert lifecycle.last_inbound_at is not None
    assert lifecycle.last_outbound_at is None
    assert lifecycle.completed_at is None


def test_run_lifecycle_sweeps_marks_missing_topic_deleted_and_removes_lifecycle() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_topic_lifecycle(
        TopicLifecycle(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            bound_at=1.0,
        )
    )
    telegram = DummyTelegramClient()
    telegram.dead_topics.add((-100100, 77))
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.run_lifecycle_sweeps(now_monotonic=60.0, now_epoch=60.0)

    assert state.get_binding_by_thread("thread-1").binding_status == DELETED_BINDING_STATUS
    assert state.get_topic_lifecycle("thread-1") is None


def test_run_lifecycle_sweeps_autocloses_completed_topic_after_timeout() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_topic_lifecycle(
        TopicLifecycle(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            bound_at=1.0,
            completed_at=10.0,
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            sync_mode="assistant_plus_alerts",
            lifecycle_autoclose_after_seconds=30.0,
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.run_lifecycle_sweeps(now_monotonic=60.0, now_epoch=45.0)

    assert telegram.closed_topics == [(-100100, 77)]
    assert state.get_binding_by_thread("thread-1").binding_status == CLOSED_BINDING_STATUS


def test_run_lifecycle_sweeps_expires_unbound_topic_after_ttl() -> None:
    state = DummyState()
    state.upsert_topic_project(
        TopicProject(
            chat_id=-100100,
            message_thread_id=91,
            topic_name="Unbound topic",
            project_id="/Users/kangmo/sacle/src/gateway-project",
            picker_message_id=12,
        )
    )
    state.set_topic_project_last_seen(-100100, 91, 10.0)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            sync_mode="assistant_plus_alerts",
            lifecycle_unbound_ttl_seconds=30.0,
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.run_lifecycle_sweeps(now_monotonic=60.0, now_epoch=45.0)

    assert telegram.closed_topics == [(-100100, 91)]
    assert state.get_topic_project(-100100, 91) is None
    assert state.get_topic_project_last_seen(-100100, 91) is None


def test_run_lifecycle_sweeps_prunes_orphan_topic_history() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.record_topic_history(-100100, 77, text="keep me")
    state.record_topic_history(-100100, 88, text="delete me")
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            sync_mode="assistant_plus_alerts",
            lifecycle_prune_interval_seconds=30.0,
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.run_lifecycle_sweeps(now_monotonic=45.0, now_epoch=45.0)

    assert state.list_topic_history(-100100, 77) == [TopicHistoryEntry(text="keep me")]
    assert state.list_topic_history(-100100, 88) == []


def test_sync_codex_once_processes_mirror_topic_creation_jobs() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_topic_creation_job(
        TopicCreationJob(
            codex_thread_id="thread-1",
            chat_id=-100200,
            topic_name="(gateway-project) thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            telegram_mirror_chat_ids=(-100200,),
            sync_mode="assistant_plus_alerts",
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    mirror_binding = state.get_mirror_binding_by_topic(-100200, 1)
    assert mirror_binding is not None
    assert mirror_binding.codex_thread_id == "thread-1"
    assert state.get_topic_creation_job("thread-1", -100200) is None
    assert telegram.created_topics == [(-100200, "(gateway-project) thread-1")]


def test_sync_codex_once_retries_mirror_topic_creation_after_retry_after(monkeypatch) -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_topic_creation_job(
        TopicCreationJob(
            codex_thread_id="thread-1",
            chat_id=-100200,
            topic_name="(gateway-project) thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            telegram_mirror_chat_ids=(-100200,),
            sync_mode="assistant_plus_alerts",
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    monkeypatch.setattr("codex_telegram_gateway.daemon.time.time", lambda: 100.0)

    def fail_create_forum_topic(chat_id: int, name: str) -> int:
        del chat_id, name
        raise TelegramRetryAfterError(
            "createForumTopic",
            27,
            {"ok": False, "parameters": {"retry_after": 27}},
        )

    telegram.create_forum_topic = fail_create_forum_topic

    daemon.sync_codex_once()

    retry_job = state.get_topic_creation_job("thread-1", -100200)
    assert retry_job is not None
    assert retry_job.retry_after_at == 128.0


def test_sync_codex_once_mirrors_assistant_output_to_secondary_chat() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_mirror_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100200,
            message_thread_id=88,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="Completed the refactor.",
        )
    )
    daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            telegram_mirror_chat_ids=(-100200,),
            sync_mode="assistant_plus_alerts",
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert telegram.sent_messages == [
        (-100100, 77, "Completed the refactor.", None),
        (-100200, 88, "Completed the refactor.", None),
    ]


def test_poll_telegram_once_routes_message_from_mirror_topic_to_same_thread() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_mirror_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100200,
            message_thread_id=88,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100200,
        message_thread_id=88,
        from_user_id=111,
        text="Please continue from mirror chat.",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            telegram_mirror_chat_ids=(-100200,),
            sync_mode="assistant_plus_alerts",
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.list_pending_inbound() == [
        InboundMessage(
            telegram_update_id=1,
            chat_id=-100200,
            message_thread_id=88,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Please continue from mirror chat.",
        )
    ]


def test_poll_telegram_once_gateway_bindings_dashboard_lists_mirrors_and_pending_jobs() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_mirror_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100200,
            message_thread_id=88,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    state.upsert_topic_creation_job(
        TopicCreationJob(
            codex_thread_id="thread-2",
            chat_id=-100300,
            topic_name="(another-project) untitled",
            project_id="/Users/kangmo/sacle/src/another-project",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway bindings",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            telegram_mirror_chat_ids=(-100200, -100300),
            sync_mode="assistant_plus_alerts",
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert "mirror chat `-100200` topic `88`" in telegram.sent_messages[0][2]
    assert "Pending mirror topic creation" in telegram.sent_messages[0][2]
