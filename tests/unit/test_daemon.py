from dataclasses import replace
import time
import pytest
from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.daemon import GatewayDaemon, _mirror_control_text, _parse_topic_name
from codex_telegram_gateway.history_command import CALLBACK_HISTORY_PREFIX
from codex_telegram_gateway.live_view import LiveViewState, capture_hash_for_path
from codex_telegram_gateway.recovery import (
    CALLBACK_RESTORE_CANCEL,
    CALLBACK_RESTORE_CONTINUE,
    CALLBACK_RESTORE_RECREATE,
    CALLBACK_RESTORE_RESUME,
)
from codex_telegram_gateway.resume_command import (
    CALLBACK_RESUME_CANCEL,
    CALLBACK_RESUME_PAGE_PREFIX,
    CALLBACK_RESUME_PICK_PREFIX,
)
from codex_telegram_gateway.toolbar import CALLBACK_TOOLBAR_PREFIX
from pathlib import Path
from codex_telegram_gateway.telegram_api import TelegramApiError, TelegramRetryAfterError

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
    InteractivePromptViewState,
    OutboundMessage,
    PendingTurn,
    RestoreViewState,
    ResumeViewState,
    SendViewState,
    StatusBubbleViewState,
    StartedTurn,
    ToolbarViewState,
    TopicCreationJob,
    TopicLifecycle,
    TopicHistoryEntry,
    TopicProject,
    TurnResult,
    VoicePromptViewState,
)

from tests.unit.support import DummyCodexBridge, DummyState, DummyTelegramClient


class StaticTranscriptionProvider:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list[str] = []

    def transcribe(self, audio_path: Path):
        self.calls.append(str(audio_path))
        return __import__("codex_telegram_gateway.voice_ingest", fromlist=["TranscriptionResult"]).TranscriptionResult(
            text=self.text,
            language="en",
        )


class StaticScreenshotProvider:
    def __init__(self, file_path: Path, *, send_as_document: bool = False) -> None:
        self.file_path = file_path
        self.send_as_document = send_as_document
        self.calls: list[tuple[str, str, str | None]] = []

    def capture_thread(self, *, thread_id: str, thread_title: str, project_id: str | None):
        self.calls.append((thread_id, thread_title, project_id))
        return __import__("codex_telegram_gateway.screenshot_capture", fromlist=["ScreenshotCapture"]).ScreenshotCapture(
            file_path=self.file_path,
            send_as_document=self.send_as_document,
        )


class SequencedScreenshotProvider:
    def __init__(self, file_paths: list[Path]) -> None:
        self.file_paths = list(file_paths)
        self.calls: list[tuple[str, str, str | None]] = []

    def capture_thread(self, *, thread_id: str, thread_title: str, project_id: str | None):
        self.calls.append((thread_id, thread_title, project_id))
        capture_path = self.file_paths[min(len(self.calls) - 1, len(self.file_paths) - 1)]
        return __import__("codex_telegram_gateway.screenshot_capture", fromlist=["ScreenshotCapture"]).ScreenshotCapture(
            file_path=capture_path,
            send_as_document=False,
        )


class MissingFileScreenshotProvider:
    def __init__(self, file_path: Path) -> None:
        self.file_path = file_path
        self.calls: list[tuple[str, str, str | None]] = []

    def capture_thread(self, *, thread_id: str, thread_title: str, project_id: str | None):
        self.calls.append((thread_id, thread_title, project_id))
        return __import__("codex_telegram_gateway.screenshot_capture", fromlist=["ScreenshotCapture"]).ScreenshotCapture(
            file_path=self.file_path,
            send_as_document=False,
        )


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


def make_config(**overrides) -> GatewayConfig:
    return GatewayConfig(
        telegram_bot_token="token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
        **overrides,
    )


def write_toolbar_config(path: Path) -> Path:
    path.write_text(
        "\n".join(
            [
                '[actions.status]',
                'emoji = "📍"',
                'text = "Status"',
                'type = "gateway_command"',
                'payload = "status"',
                "",
                "[actions.compact]",
                'emoji = "🧹"',
                'text = "Compact"',
                'type = "thread_text"',
                'payload = "/compact"',
                "",
                "[actions.steer]",
                'emoji = "🧭"',
                'text = "Steer"',
                'type = "steer_template"',
                'payload = "Focus on the last user request and continue."',
                "",
                "[actions.dismiss]",
                'emoji = "✖"',
                'text = "Close"',
                'type = "builtin"',
                'payload = "dismiss"',
                "",
                "[layout]",
                'style = "text"',
                'buttons = [["status", "compact"], ["steer", "dismiss"]]',
            ]
        )
    )
    return path


def non_bubble_sent_messages(telegram: DummyTelegramClient) -> list[tuple[int, int, str, dict[str, object] | None]]:
    return [
        message
        for message in telegram.sent_messages
        if not message[2].startswith("Topic status\n\n")
    ]


def non_bubble_edited_messages(
    telegram: DummyTelegramClient,
) -> list[tuple[int, int, str, dict[str, object] | None]]:
    return [
        message
        for message in telegram.edited_messages
        if not message[2].startswith("Topic status\n\n")
    ]


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

    assert non_bubble_sent_messages(telegram) == [(-100100, 77, "Completed the refactor.", None)]
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

    assert non_bubble_sent_messages(telegram) == [(-100100, 77, "I found the first issue.", None)]
    assert non_bubble_edited_messages(telegram) == [
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

    assert non_bubble_sent_messages(telegram) == []
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
                "/gateway upgrade - Show plugin version and upgrade instructions\n"
                "/gateway recall - Recall recent topic messages\n"
                "/gateway history - Show paginated history for this Codex thread\n"
                "/gateway resume - Resume another Codex thread from this project\n"
                    "/gateway restore - Show recovery options for this topic\n"
                "/gateway unbind - Detach this Telegram topic from its Codex thread\n"
                "/gateway bindings - List Codex thread to Telegram topic bindings\n"
                "/gateway create_thread - Create a new Codex thread in this topic\n"
                "/gateway screenshot - Capture the current Codex App window for this thread\n"
                "/gateway live - Start or refresh a live Codex App window feed\n"
                "/gateway send - Browse project files and send one back to Telegram\n"
                "/gateway verbose - Change supplemental Telegram notification mode\n"
                "/gateway project - Choose or switch the Codex project for this topic\n"
                "/gateway status - Show the current topic binding and thread status\n"
                "/gateway sync - Audit bindings and recover deleted topics\n"
                "/gateway toolbar - Show or refresh the topic action bar\n"
            "/gateway help - Show available gateway commands\n\n"
            "Telegram menu commands:\n"
            "/gateway - Gateway control commands and status\n"
            "Additional pass-through commands appear here after you use them or configure them.\n\n"
            "Compatibility aliases inside `/gateway`: new, start, sessions, commands\n"
            "All other slash commands are passed through to the bound Codex thread unchanged.",
            None,
        )
    ]


def test_poll_telegram_once_gateway_upgrade_sends_rendered_diagnostics(monkeypatch) -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway upgrade",
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
    diagnostics = __import__("codex_telegram_gateway.upgrade_diagnostics", fromlist=["UpgradeDiagnostics"]).UpgradeDiagnostics(
        plugin_name="codex-telegram-gateway",
        version="0.1.0",
        plugin_root="/tmp/plugin",
        plugin_manifest_path="/tmp/plugin/.codex-plugin/plugin.json",
        mcp_manifest_path="/tmp/plugin/.mcp.json",
    )
    monkeypatch.setattr("codex_telegram_gateway.daemon.discover_upgrade_diagnostics", lambda start_path: diagnostics)
    monkeypatch.setattr("codex_telegram_gateway.daemon.render_upgrade_text", lambda info: f"upgrade:{info.version}")

    daemon.poll_telegram_once()

    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "upgrade:0.1.0",
            None,
        )
    ]


def test_poll_telegram_once_gateway_upgrade_reports_discovery_failure(monkeypatch) -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway upgrade",
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
    monkeypatch.setattr(
        "codex_telegram_gateway.daemon.discover_upgrade_diagnostics",
        lambda start_path: (_ for _ in ()).throw(FileNotFoundError("missing manifest")),
    )

    daemon.poll_telegram_once()

    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "Upgrade diagnostics failed: missing manifest",
            None,
        )
    ]


def test_poll_telegram_once_gateway_toolbar_sends_and_refreshes_persisted_view(tmp_path) -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway toolbar",
    )
    toolbar_config_path = write_toolbar_config(tmp_path / "toolbar.toml")
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(toolbar_config_path=toolbar_config_path),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert non_bubble_sent_messages(telegram) == [
        (
            -100100,
            77,
            "Topic toolbar\n\nProject: `gateway-project`\nThread id: `thread-1`",
            {
                "inline_keyboard": [
                    [
                        {"text": "Status", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}status"},
                        {"text": "Compact", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}compact"},
                    ],
                    [
                        {"text": "Steer", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}steer"},
                        {"text": "Close", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}dismiss"},
                    ],
                ]
            },
        )
    ]
    assert state.get_toolbar_view(-100100, 77) == ToolbarViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        codex_thread_id="thread-1",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )

    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway toolbar",
    )
    daemon.poll_telegram_once()

    assert non_bubble_edited_messages(telegram)[-1] == (
        -100100,
        1,
        "Topic toolbar\n\nProject: `gateway-project`\nThread id: `thread-1`",
        {
            "inline_keyboard": [
                [
                    {"text": "Status", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}status"},
                    {"text": "Compact", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}compact"},
                ],
                [
                    {"text": "Steer", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}steer"},
                    {"text": "Close", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}dismiss"},
                ],
            ]
        },
    )


def test_poll_telegram_once_toolbar_status_callback_routes_to_gateway_command(tmp_path) -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    toolbar_config_path = write_toolbar_config(tmp_path / "toolbar.toml")
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(toolbar_config_path=toolbar_config_path),
        state=state,
        telegram=telegram,
        codex=codex,
    )
    state.upsert_toolbar_view(
        ToolbarViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-toolbar-status",
        chat_id=-100100,
        message_thread_id=77,
        message_id=9,
        from_user_id=111,
        data=f"{CALLBACK_TOOLBAR_PREFIX}status",
    )

    daemon.poll_telegram_once()

    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "Topic status\n\n"
            "Project: `gateway-project`\n"
            "Thread title: `thread-1`\n"
            "Thread id: `thread-1`\n"
            "Topic id: `77`\n"
            "Notification mode: `all`\n"
            "Codex status: `idle`",
            None,
        )
    ]
    assert telegram.answered_callback_queries == [("cb-toolbar-status", "Ran status.")]


def test_poll_telegram_once_toolbar_thread_text_callback_enqueues_bound_inbound(tmp_path) -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    toolbar_config_path = write_toolbar_config(tmp_path / "toolbar.toml")
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(toolbar_config_path=toolbar_config_path),
        state=state,
        telegram=telegram,
        codex=codex,
    )
    state.upsert_toolbar_view(
        ToolbarViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-toolbar-compact",
        chat_id=-100100,
        message_thread_id=77,
        message_id=9,
        from_user_id=111,
        data=f"{CALLBACK_TOOLBAR_PREFIX}compact",
    )

    daemon.poll_telegram_once()

    assert state.list_pending_inbound() == [
        InboundMessage(
            telegram_update_id=1,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="/compact",
        )
    ]
    assert telegram.answered_callback_queries == [("cb-toolbar-compact", "Queued.")]


def test_poll_telegram_once_toolbar_steer_callback_steers_active_turn(tmp_path) -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-9",
        )
    )
    telegram = DummyTelegramClient()
    toolbar_config_path = write_toolbar_config(tmp_path / "toolbar.toml")
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(toolbar_config_path=toolbar_config_path),
        state=state,
        telegram=telegram,
        codex=codex,
    )
    state.upsert_toolbar_view(
        ToolbarViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-toolbar-steer",
        chat_id=-100100,
        message_thread_id=77,
        message_id=9,
        from_user_id=111,
        data=f"{CALLBACK_TOOLBAR_PREFIX}steer",
    )

    daemon.poll_telegram_once()

    assert codex.steered_turns == [
        (
            "turn-9",
            StartedTurn(
                thread_id="thread-1",
                text="Focus on the last user request and continue.",
            ),
        )
    ]
    assert telegram.answered_callback_queries == [("cb-toolbar-steer", "Steered.")]


def test_poll_telegram_once_toolbar_dismiss_callback_clears_persisted_view(tmp_path) -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    toolbar_config_path = write_toolbar_config(tmp_path / "toolbar.toml")
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(toolbar_config_path=toolbar_config_path),
        state=state,
        telegram=telegram,
        codex=codex,
    )
    state.upsert_toolbar_view(
        ToolbarViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-toolbar-dismiss",
        chat_id=-100100,
        message_thread_id=77,
        message_id=9,
        from_user_id=111,
        data=f"{CALLBACK_TOOLBAR_PREFIX}dismiss",
    )

    daemon.poll_telegram_once()

    assert state.get_toolbar_view(-100100, 77) is None
    assert telegram.edited_reply_markups == [(-100100, 9, None)]
    assert telegram.answered_callback_queries == [("cb-toolbar-dismiss", "Dismissed.")]


def test_poll_telegram_once_gateway_verbose_opens_notification_mode_picker() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway verbose",
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
            "Notification mode\n\n"
            "Current: `all`\n\n"
            "- `all`: typing and routine status chatter\n"
            "- `important`: only important alerts and errors\n"
            "- `errors_only`: only errors\n"
            "- `muted`: suppress supplemental chatter",
            {
                "inline_keyboard": [
                    [{"text": "✓ Bell All", "callback_data": "gw:verbose:set:all"}],
                    [{"text": "Mention Important", "callback_data": "gw:verbose:set:important"}],
                    [{"text": "Warning Errors Only", "callback_data": "gw:verbose:set:errors_only"}],
                    [{"text": "Silent Muted", "callback_data": "gw:verbose:set:muted"}],
                    [{"text": "Dismiss", "callback_data": "gw:verbose:dismiss"}],
                ]
            },
        )
    ]


def test_poll_telegram_once_gateway_verbose_callback_updates_binding_mode() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway verbose",
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
        update_id=2,
        callback_query_id="cb-verbose-set",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:verbose:set:errors_only",
    )
    daemon.poll_telegram_once()

    assert state.get_binding_by_thread("thread-1").sync_mode == "errors_only"
    assert telegram.edited_messages[-1] == (
        -100100,
        1,
        "Notification mode\n\n"
        "Current: `errors_only`\n\n"
        "- `all`: typing and routine status chatter\n"
        "- `important`: only important alerts and errors\n"
        "- `errors_only`: only errors\n"
        "- `muted`: suppress supplemental chatter",
        {
            "inline_keyboard": [
                [{"text": "Bell All", "callback_data": "gw:verbose:set:all"}],
                [{"text": "Mention Important", "callback_data": "gw:verbose:set:important"}],
                [{"text": "✓ Warning Errors Only", "callback_data": "gw:verbose:set:errors_only"}],
                [{"text": "Silent Muted", "callback_data": "gw:verbose:set:muted"}],
                [{"text": "Dismiss", "callback_data": "gw:verbose:dismiss"}],
            ]
        },
    )
    assert telegram.answered_callback_queries[-1] == ("cb-verbose-set", "Warning Errors Only")


def test_poll_telegram_once_gateway_verbose_dismiss_clears_markup() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway verbose",
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
        update_id=2,
        callback_query_id="cb-verbose-dismiss",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:verbose:dismiss",
    )
    daemon.poll_telegram_once()

    assert telegram.edited_reply_markups[-1] == (-100100, 1, None)
    assert telegram.answered_callback_queries[-1] == ("cb-verbose-dismiss", "Dismissed.")


def test_poll_telegram_once_gateway_verbose_rejects_unbound_topic() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway verbose",
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

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "This topic is not bound to any Codex thread.",
        None,
    )


def test_poll_telegram_once_gateway_status_shows_notification_mode() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway status",
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

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "Topic status\n\n"
        "Project: `gateway-project`\n"
        "Thread title: `thread-1`\n"
        "Thread id: `thread-1`\n"
        "Topic id: `77`\n"
        "Notification mode: `all`\n"
        "Codex status: `idle`",
        None,
    )


def test_poll_telegram_once_gateway_unbind_detaches_primary_and_mirror_topics() -> None:
    state = DummyState()
    primary = make_binding()
    mirror = Binding(
        codex_thread_id="thread-1",
        chat_id=-100200,
        message_thread_id=88,
        topic_name="🟢 (gateway-project) thread-1",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )
    state.create_binding(primary)
    state.upsert_mirror_binding(mirror)
    state.enqueue_inbound(
        InboundMessage(
            telegram_update_id=9,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="queued before unbind",
        )
    )
    state.record_topic_history(-100100, 77, text="recent primary message")
    state.record_topic_history(-100200, 88, text="recent mirror message")
    state.upsert_history_view(
        HistoryViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=41,
            codex_thread_id="thread-1",
            page_index=0,
        )
    )
    state.upsert_resume_view(
        ResumeViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=42,
            project_id="/Users/kangmo/sacle/src/gateway-project",
            page_index=0,
        )
    )
    state.upsert_send_view(
        SendViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=43,
            codex_thread_id="thread-1",
            project_root="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    state.upsert_send_view(
        SendViewState(
            chat_id=-100200,
            message_thread_id=88,
            message_id=44,
            codex_thread_id="thread-1",
            project_root="/Users/kangmo/sacle/src/gateway-project",
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
    state.upsert_outbound_message(
        OutboundMessage(
            codex_thread_id="thread-1",
            event_id="event-1",
            telegram_message_ids=(101,),
            text="assistant output",
        )
    )
    state.upsert_mirror_outbound_message(
        OutboundMessage(
            codex_thread_id="thread-1",
            event_id="event-1",
            telegram_message_ids=(202,),
            text="assistant output",
        ),
        chat_id=-100200,
        message_thread_id=88,
    )
    state.upsert_topic_creation_job(
        TopicCreationJob(
            codex_thread_id="thread-1",
            chat_id=-100300,
            topic_name="(gateway-project) thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway unbind",
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
        config=make_config(telegram_mirror_chat_ids=(-100200,)),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.get_binding_by_topic(-100100, 77) is None
    with pytest.raises(KeyError):
        state.get_binding_by_thread("thread-1")
    assert state.list_mirror_bindings_for_thread("thread-1") == []
    assert state.pending_inbound_count() == 0
    assert state.get_pending_turn("thread-1") is None
    assert state.get_outbound_message("thread-1", "event-1") is None
    assert state.get_mirror_outbound_message(
        "thread-1",
        "event-1",
        chat_id=-100200,
        message_thread_id=88,
    ) is None
    assert state.list_topic_creation_jobs() == []
    assert state.get_history_view(-100100, 77) is None
    assert state.get_resume_view(-100100, 77) is None
    assert state.get_send_view(-100100, 77) is None
    assert state.get_send_view(-100200, 88) is None
    assert state.list_topic_history(-100100, 77) == []
    assert state.list_topic_history(-100200, 88) == []
    assert state.get_topic_project(-100100, 77) == TopicProject(
        chat_id=-100100,
        message_thread_id=77,
        topic_name="(gateway-project) thread-1",
        project_id=None,
        picker_message_id=None,
    )
    assert state.get_topic_project(-100200, 88) == TopicProject(
        chat_id=-100200,
        message_thread_id=88,
        topic_name="(gateway-project) thread-1",
        project_id=None,
        picker_message_id=None,
    )
    assert state.get_topic_project_last_seen(-100100, 77) is not None
    assert state.get_topic_project_last_seen(-100200, 88) is not None
    assert telegram.edited_topics == [
        (-100100, 77, "(gateway-project) thread-1"),
        (-100200, 88, "(gateway-project) thread-1"),
    ]
    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "✂ Unbound this topic from Codex thread.\n\n"
            "Thread title: `thread-1`\n"
            "Thread id: `thread-1`\n"
            "Detached `1` mirror topic(s) for the same Codex thread.\n"
            "The Codex thread is still available in Codex App.\n"
            "Send a message in this topic to choose a project and create or bind a new thread.",
            None,
        )
    ]


def test_poll_telegram_once_gateway_unbind_rejects_mirror_topic_controls() -> None:
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
        text="/gateway unbind",
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
        config=make_config(telegram_mirror_chat_ids=(-100200,)),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.get_binding_by_thread("thread-1").message_thread_id == 77
    assert state.get_mirror_binding_by_topic(-100200, 88) is not None
    assert telegram.sent_messages == [(-100200, 88, _mirror_control_text(), None)]


def test_poll_telegram_once_gateway_restore_opens_menu_for_closed_binding() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway restore",
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
            "Recovery options\n\n"
            "Topic: `(gateway-project) thread-1`\n"
            "Thread id: `thread-1`\n\n"
            "This topic is currently marked closed, so new messages are not being routed to Codex.\n"
            "Choose how to restore it.",
            {
                "inline_keyboard": [
                    [
                        {"text": "Continue Here", "callback_data": CALLBACK_RESTORE_CONTINUE},
                        {"text": "Resume Other Thread", "callback_data": CALLBACK_RESTORE_RESUME},
                    ],
                    [{"text": "Cancel", "callback_data": CALLBACK_RESTORE_CANCEL}],
                ]
            },
        )
    ]
    assert state.get_restore_view(-100100, 77) == RestoreViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        codex_thread_id="thread-1",
        issue_kind="closed",
    )


def test_poll_telegram_once_closed_binding_message_shows_restore_prompt() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
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

    assert state.pending_inbound_count() == 0
    assert telegram.sent_messages[0][2].startswith("Recovery options")
    assert state.get_restore_view(-100100, 77) is not None


def test_poll_telegram_once_restore_continue_reactivates_closed_binding() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="closed",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-restore-continue",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data=CALLBACK_RESTORE_CONTINUE,
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

    assert state.get_binding_by_thread("thread-1").binding_status == ACTIVE_BINDING_STATUS
    assert state.get_restore_view(-100100, 77) is None
    assert telegram.edited_messages == [
        (
            -100100,
            15,
            "Restored this topic in place.\nThread id: `thread-1`",
            None,
        )
    ]
    assert telegram.answered_callback_queries == [("cb-restore-continue", "Restored.")]


def test_poll_telegram_once_restore_recreate_recovers_deleted_binding() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=DELETED_BINDING_STATUS))
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="deleted",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-restore-recreate",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data=CALLBACK_RESTORE_RECREATE,
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

    rebound = state.get_binding_by_thread("thread-1")
    assert rebound.binding_status == ACTIVE_BINDING_STATUS
    assert rebound.message_thread_id == 1
    assert state.get_restore_view(-100100, 77) is None
    assert telegram.created_topics == [(-100100, "(gateway-project) thread-1")]
    assert telegram.edited_messages == [
        (
            -100100,
            15,
            "Recreated the Telegram topic for this Codex thread.\n"
            "New topic id: `1`\n"
            "Thread id: `thread-1`",
            None,
        )
    ]
    assert telegram.answered_callback_queries == [("cb-restore-recreate", "Recreated.")]


def test_poll_telegram_once_restore_resume_reuses_resume_picker() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="closed",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-restore-resume",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data=CALLBACK_RESTORE_RESUME,
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.create_thread("/Users/kangmo/sacle/src/gateway-project", "older thread")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.get_restore_view(-100100, 77) is None
    assert state.get_resume_view(-100100, 77) == ResumeViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        project_id="/Users/kangmo/sacle/src/gateway-project",
        page_index=0,
    )
    assert telegram.edited_messages == [
        (
            -100100,
            15,
            "⏪ Resume Codex Thread\n\n"
            "Project: `gateway-project`\n"
            "Available threads: `1`\n\n"
            "Choose an existing thread to bind to this topic.",
            {
                "inline_keyboard": [
                    [{"text": "🟢 older thread", "callback_data": "gw:resume:pick:thread-2"}],
                    [{"text": "1/1", "callback_data": "tp:noop"}],
                    [{"text": "Cancel", "callback_data": "gw:resume:cancel"}],
                ]
            },
        )
    ]
    assert telegram.answered_callback_queries == [("cb-restore-resume", "Choose a thread.")]


def test_poll_telegram_once_gateway_restore_reports_unbound_topic() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway restore",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.sent_messages == [(-100100, 77, "This topic is not bound to any Codex thread.", None)]


def test_poll_telegram_once_gateway_restore_reports_healthy_topic() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=99,
            codex_thread_id="thread-1",
            issue_kind="closed",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway restore",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert state.get_restore_view(-100100, 77) is None
    assert telegram.sent_messages == [(-100100, 77, "Nothing to restore. This topic is already healthy.", None)]


def test_poll_telegram_once_restore_cancel_clears_menu() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="closed",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-restore-cancel",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data=CALLBACK_RESTORE_CANCEL,
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert state.get_restore_view(-100100, 77) is None
    assert telegram.edited_reply_markups == [(-100100, 15, None)]
    assert telegram.answered_callback_queries == [("cb-restore-cancel", "Cancelled.")]


def test_poll_telegram_once_restore_callback_rejects_unbound_or_stale_menu() -> None:
    state = DummyState()
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="closed",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-restore-unbound",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data=CALLBACK_RESTORE_CONTINUE,
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    state.delete_binding("thread-1")
    daemon.poll_telegram_once()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="closed",
        )
    )
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-restore-stale",
        chat_id=-100100,
        message_thread_id=77,
        message_id=99,
        from_user_id=111,
        data=CALLBACK_RESTORE_CONTINUE,
    )
    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries == [
        ("cb-restore-unbound", "This topic is no longer eligible for recovery."),
        ("cb-restore-stale", "This recovery menu is stale."),
    ]


def test_poll_telegram_once_restore_callback_handles_issue_drift_and_unknown_actions() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="deleted",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-restore-refresh",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data=CALLBACK_RESTORE_CONTINUE,
    )
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-restore-unknown",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:restore:unknown",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="closed",
        )
    )
    daemon.poll_telegram_once()

    assert telegram.edited_messages[0][2].startswith("Recovery options")
    assert telegram.answered_callback_queries == [
        ("cb-restore-refresh", "Recovery state changed. Refreshed."),
        ("cb-restore-unknown", "Unknown recovery action."),
    ]


def test_poll_telegram_once_restore_callback_rejects_wrong_issue_actions_and_healthy_state() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=DELETED_BINDING_STATUS))
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="deleted",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-restore-wrong-continue",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data=CALLBACK_RESTORE_CONTINUE,
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="closed",
        )
    )
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-restore-wrong-recreate",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data=CALLBACK_RESTORE_RECREATE,
    )
    daemon.poll_telegram_once()
    state.create_binding(make_binding())
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="closed",
        )
    )
    telegram.push_callback_query(
        update_id=3,
        callback_query_id="cb-restore-healthy",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data=CALLBACK_RESTORE_CONTINUE,
    )
    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries == [
        ("cb-restore-wrong-continue", "Continue here is not available for this issue."),
        ("cb-restore-wrong-recreate", "Recreate is not available for this issue."),
        ("cb-restore-healthy", "Already healthy."),
    ]
    assert telegram.edited_messages[-1] == (
        -100100,
        15,
        "Nothing to restore. This topic is already healthy.",
        None,
    )


def test_poll_telegram_once_closed_binding_reuses_existing_restore_prompt_message() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    state.upsert_restore_view(
        RestoreViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            issue_kind="closed",
        )
    )
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
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.sent_messages == []
    assert telegram.edited_messages == [
        (
            -100100,
            15,
            "Recovery options\n\n"
            "Topic: `(gateway-project) thread-1`\n"
            "Thread id: `thread-1`\n\n"
            "This topic is currently marked closed, so new messages are not being routed to Codex.\n"
            "Choose how to restore it.",
            {
                "inline_keyboard": [
                    [
                        {"text": "Continue Here", "callback_data": CALLBACK_RESTORE_CONTINUE},
                        {"text": "Resume Other Thread", "callback_data": CALLBACK_RESTORE_RESUME},
                    ],
                    [{"text": "Cancel", "callback_data": CALLBACK_RESTORE_CANCEL}],
                ]
            },
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


def test_poll_telegram_once_gateway_resume_opens_picker() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway resume",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="current thread",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.create_thread("/Users/kangmo/sacle/src/gateway-project", "older thread")
    codex.create_thread("/Users/kangmo/sacle/src/gateway-project", "other thread")
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
            "⏪ Resume Codex Thread\n\n"
            "Project: `gateway-project`\n"
            "Available threads: `2`\n\n"
            "Choose an existing thread to bind to this topic.",
            {
                "inline_keyboard": [
                    [{"text": "🟢 older thread", "callback_data": f"{CALLBACK_RESUME_PICK_PREFIX}thread-2"}],
                    [{"text": "🟢 other thread", "callback_data": f"{CALLBACK_RESUME_PICK_PREFIX}thread-3"}],
                    [{"text": "1/1", "callback_data": "tp:noop"}],
                    [{"text": "Cancel", "callback_data": CALLBACK_RESUME_CANCEL}],
                ]
            },
        )
    ]
    assert state.get_resume_view(-100100, 77) == ResumeViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        project_id="/Users/kangmo/sacle/src/gateway-project",
        page_index=0,
    )


def test_poll_telegram_once_resume_pick_rebinds_topic_without_replaying_history() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_resume_view(
        ResumeViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            project_id="/Users/kangmo/sacle/src/gateway-project",
            page_index=0,
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-resume-pick",
        chat_id=-100100,
        message_thread_id=77,
        message_id=9,
        from_user_id=111,
        data=f"{CALLBACK_RESUME_PICK_PREFIX}thread-2",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="current thread",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.create_thread("/Users/kangmo/sacle/src/gateway-project", "older thread")
    codex.append_event(
        CodexEvent(
            event_id="thread-2:event-1",
            thread_id="thread-2",
            kind="assistant_message",
            text="existing history",
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
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    rebound = state.get_binding_by_topic(-100100, 77)
    assert rebound.codex_thread_id == "thread-2"
    assert state.has_seen_event("thread-2", "thread-2:event-1") is True
    assert state.get_pending_turn("thread-1") is None
    assert state.get_resume_view(-100100, 77) is None
    assert telegram.edited_topics == [(-100100, 77, "(gateway-project) older thread")]
    assert telegram.edited_messages == [
        (
            -100100,
            9,
            "Resumed this topic into `older thread`.\nThread id: `thread-2`",
            None,
        )
    ]
    assert telegram.answered_callback_queries == [("cb-resume-pick", "Resumed.")]


def test_poll_telegram_once_resume_cancel_clears_picker() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_resume_view(
        ResumeViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            project_id="/Users/kangmo/sacle/src/gateway-project",
            page_index=0,
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-resume-cancel",
        chat_id=-100100,
        message_thread_id=77,
        message_id=9,
        from_user_id=111,
        data=CALLBACK_RESUME_CANCEL,
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="current thread",
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

    assert state.get_resume_view(-100100, 77) is None
    assert telegram.edited_reply_markups == [(-100100, 9, None)]
    assert telegram.answered_callback_queries == [("cb-resume-cancel", "Cancelled.")]


def test_poll_telegram_once_resume_page_edits_existing_picker() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_resume_view(
        ResumeViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            project_id="/Users/kangmo/sacle/src/gateway-project",
            page_index=0,
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=3,
        callback_query_id="cb-resume-page",
        chat_id=-100100,
        message_thread_id=77,
        message_id=9,
        from_user_id=111,
        data=f"{CALLBACK_RESUME_PAGE_PREFIX}1",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="current thread",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    for index in range(9):
        codex.create_thread(
            "/Users/kangmo/sacle/src/gateway-project",
            f"thread {index}",
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
            9,
            "⏪ Resume Codex Thread\n\n"
            "Project: `gateway-project`\n"
            "Available threads: `9`\n\n"
            "Choose an existing thread to bind to this topic.",
            {
                "inline_keyboard": [
                    [{"text": "🟢 thread 6", "callback_data": f"{CALLBACK_RESUME_PICK_PREFIX}thread-8"}],
                    [{"text": "🟢 thread 7", "callback_data": f"{CALLBACK_RESUME_PICK_PREFIX}thread-9"}],
                    [{"text": "🟢 thread 8", "callback_data": f"{CALLBACK_RESUME_PICK_PREFIX}thread-10"}],
                    [
                        {"text": "◀ Prev", "callback_data": f"{CALLBACK_RESUME_PAGE_PREFIX}0"},
                        {"text": "2/2", "callback_data": "tp:noop"},
                    ],
                    [{"text": "Cancel", "callback_data": CALLBACK_RESUME_CANCEL}],
                ]
            },
        )
    ]
    assert state.get_resume_view(-100100, 77) == ResumeViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=9,
        project_id="/Users/kangmo/sacle/src/gateway-project",
        page_index=1,
    )
    assert telegram.answered_callback_queries == [("cb-resume-page", "Page updated.")]


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
            "Gateway sessions\n"
            "Page 1/1 • 1 binding\n\n"
            "1. 🟢 `(gateway-project) thread-1`\n"
            "project `gateway-project` • thread `thread-1`\n"
            "topic `77` • id `thread-1`\n"
            "status `idle` • notify `all`",
            {
                "inline_keyboard": [
                        [
                            {"text": "↻", "callback_data": "gw:sessions:refresh:0:-100100:77"},
                            {"text": "➕", "callback_data": "gw:sessions:new:0:-100100:77"},
                            {"text": "✂", "callback_data": "gw:sessions:unbind:0:-100100:77"},
                            {"text": "📺", "callback_data": "gw:sessions:live:0:-100100:77"},
                            {"text": "📸", "callback_data": "gw:sessions:screenshot:0:-100100:77"},
                            {"text": "♻", "callback_data": "gw:sessions:restore:0:-100100:77"},
                        ],
                    [
                        {"text": "Refresh", "callback_data": "gw:sessions:refresh:0"},
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
        data="gw:sessions:refresh:0",
    )

    daemon.poll_telegram_once()

    assert telegram.edited_messages[-1] == (
        -100100,
        1,
        "Gateway sessions\n"
        "Page 1/1 • 1 binding\n\n"
        "1. 🟢 `(gateway-project) thread-1`\n"
        "project `gateway-project` • thread `renamed thread`\n"
        "topic `77` • id `thread-1`\n"
        "status `idle` • notify `all`",
        {
            "inline_keyboard": [
                [
                    {"text": "↻", "callback_data": "gw:sessions:refresh:0:-100100:77"},
                    {"text": "➕", "callback_data": "gw:sessions:new:0:-100100:77"},
                    {"text": "✂", "callback_data": "gw:sessions:unbind:0:-100100:77"},
                    {"text": "📺", "callback_data": "gw:sessions:live:0:-100100:77"},
                    {"text": "📸", "callback_data": "gw:sessions:screenshot:0:-100100:77"},
                    {"text": "♻", "callback_data": "gw:sessions:restore:0:-100100:77"},
                ],
                [
                    {"text": "Refresh", "callback_data": "gw:sessions:refresh:0"},
                    {"text": "Dismiss", "callback_data": "gw:sessions:dismiss"},
                ]
            ]
        },
    )
    assert telegram.answered_callback_queries[-1] == ("cb-sessions", "Refreshed.")


def test_poll_telegram_once_sessions_dashboard_paginates_results() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway sessions",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    state.create_binding(make_binding())
    for index in range(2, 5):
        thread = codex.create_thread(
            "/Users/kangmo/sacle/src/gateway-project",
            thread_name=f"thread-{index}",
        )
        state.create_binding(
            Binding(
                codex_thread_id=thread.thread_id,
                chat_id=-100100,
                message_thread_id=76 + index,
                topic_name=f"(gateway-project) thread-{index}",
                sync_mode="assistant_plus_alerts",
                project_id="/Users/kangmo/sacle/src/gateway-project",
                binding_status=ACTIVE_BINDING_STATUS,
            )
        )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert "Page 1/2 • 4 bindings" in telegram.sent_messages[-1][2]
    assert telegram.sent_messages[-1][3]["inline_keyboard"][-2] == [
        {"text": "Next", "callback_data": "gw:sessions:page:1"},
    ]

    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-page-2",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:page:1",
    )

    daemon.poll_telegram_once()

    assert "Page 2/2 • 4 bindings" in telegram.edited_messages[-1][2]
    assert "1. 🟢 `(gateway-project) thread-4`" in telegram.edited_messages[-1][2]
    assert telegram.answered_callback_queries[-1] == ("cb-page-2", "Page 2.")


def test_poll_telegram_once_sessions_dashboard_dismisses_markup() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway sessions",
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
        update_id=2,
        callback_query_id="cb-dismiss",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:dismiss",
    )

    daemon.poll_telegram_once()

    assert telegram.edited_reply_markups[-1] == (-100100, 1, None)
    assert telegram.answered_callback_queries[-1] == ("cb-dismiss", "Dismissed.")


def test_poll_telegram_once_sessions_dashboard_targeted_refresh_updates_live_page() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway sessions",
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
    codex.set_thread_title("thread-1", "refreshed from row")
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-row-refresh",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:refresh:0:-100100:77",
    )

    daemon.poll_telegram_once()

    assert "thread `refreshed from row`" in telegram.edited_messages[-1][2]
    assert telegram.answered_callback_queries[-1] == ("cb-row-refresh", "Refreshed.")


def test_poll_telegram_once_sessions_dashboard_new_thread_rebinds_target_topic() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_send_view(
        SendViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_root="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway sessions",
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
        update_id=2,
        callback_query_id="cb-new",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:new:0:-100100:77",
    )

    daemon.poll_telegram_once()

    rebound = state.get_binding_by_topic(-100100, 77)
    assert rebound is not None
    assert rebound.codex_thread_id == "thread-2"
    assert codex.created_threads[-1].title == "untitled"
    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "Started a new Codex thread in gateway-project.\nThread id: `thread-2`",
        None,
    )
    assert state.get_send_view(-100100, 77) is None
    assert "1. 🟢 `(gateway-project) untitled`" in telegram.edited_messages[-1][2]
    assert "id `thread-2`" in telegram.edited_messages[-1][2]
    assert telegram.answered_callback_queries[-1] == ("cb-new", "Started a new thread.")


def test_poll_telegram_once_sessions_dashboard_unbind_requires_confirmation() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway sessions",
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
        update_id=2,
        callback_query_id="cb-unbind",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:unbind:0:-100100:77",
    )

    daemon.poll_telegram_once()

    assert telegram.edited_messages[-1] == (
        -100100,
        1,
        "Unbind this Telegram topic from Codex?\n\n"
        "Topic title: `(gateway-project) thread-1`\n"
        "Thread id: `thread-1`",
        {
            "inline_keyboard": [
                [
                    {
                        "text": "Confirm unbind",
                        "callback_data": "gw:sessions:unbind_confirm:0:-100100:77",
                    }
                ],
                [
                    {"text": "Back", "callback_data": "gw:sessions:unbind_cancel:0"},
                ],
            ]
        },
    )

    telegram.push_callback_query(
        update_id=3,
        callback_query_id="cb-unbind-cancel",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:unbind_cancel:0",
    )

    daemon.poll_telegram_once()

    assert "Gateway sessions\nPage 1/1 • 1 binding" in telegram.edited_messages[-1][2]
    assert telegram.answered_callback_queries[-1] == ("cb-unbind-cancel", "Cancelled.")

    telegram.push_callback_query(
        update_id=4,
        callback_query_id="cb-unbind-confirm",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:unbind_confirm:0:-100100:77",
    )

    daemon.poll_telegram_once()

    assert state.get_binding_by_topic(-100100, 77) is None
    assert telegram.answered_callback_queries[-1] == ("cb-unbind-confirm", "Unbound.")
    assert telegram.edited_messages[-1] == (
        -100100,
        1,
        "Gateway sessions\n\n"
        "No bound topics yet.\n"
        "Open a Telegram topic and send a message, or use `/gateway create_thread` inside a bound topic.",
        {
            "inline_keyboard": [
                [
                    {"text": "Refresh", "callback_data": "gw:sessions:refresh:0"},
                    {"text": "Dismiss", "callback_data": "gw:sessions:dismiss"},
                ]
            ]
        },
    )


def test_poll_telegram_once_sessions_dashboard_restore_recovers_closed_topic() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway sessions",
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
        update_id=2,
        callback_query_id="cb-restore",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:restore:0:-100100:77",
    )

    daemon.poll_telegram_once()

    restored = state.get_binding_by_thread("thread-1")
    assert restored.binding_status == ACTIVE_BINDING_STATUS
    assert telegram.answered_callback_queries[-1] == ("cb-restore", "Restored.")
    assert "status `idle` • notify `all`" in telegram.edited_messages[-1][2]
    assert "warning" not in telegram.edited_messages[-1][2]


def test_poll_telegram_once_sessions_dashboard_restore_reports_healthy_binding() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway sessions",
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
        update_id=2,
        callback_query_id="cb-restore-healthy",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:restore:0:-100100:77",
    )

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-restore-healthy", "Nothing to restore.")


def test_poll_telegram_once_sessions_dashboard_rejects_stale_target_topic() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway sessions",
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
        update_id=2,
        callback_query_id="cb-stale-topic",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:refresh:0:-100100:999",
    )

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == (
        "cb-stale-topic",
        "This topic is no longer bound.",
    )


def test_poll_telegram_once_gateway_screenshot_sends_photo(tmp_path) -> None:
    screenshot_path = tmp_path / "screenshot.png"
    screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway screenshot",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    screenshot_provider = StaticScreenshotProvider(screenshot_path)
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
        screenshot_provider=screenshot_provider,
    )

    daemon.poll_telegram_once()

    assert screenshot_provider.calls == [
        (
            "thread-1",
            "thread-1",
            "/Users/kangmo/sacle/src/gateway-project",
        )
    ]
    assert telegram.sent_photos == [
        (
            -100100,
            77,
            str(screenshot_path),
            "Screenshot · gateway-project / thread-1",
        )
    ]


def test_poll_telegram_once_gateway_live_sends_photo_and_persists_view(tmp_path) -> None:
    screenshot_path = tmp_path / "live.png"
    screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway live",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="running",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    screenshot_provider = StaticScreenshotProvider(screenshot_path)
    daemon = GatewayDaemon(
        config=make_config(live_view_interval_seconds=5.0),
        state=state,
        telegram=telegram,
        codex=codex,
        screenshot_provider=screenshot_provider,
    )

    daemon.poll_telegram_once()

    assert telegram.sent_photos == [
        (
            -100100,
            77,
            str(screenshot_path),
            "Live view · gateway-project / thread-1",
        )
    ]
    assert telegram.edited_reply_markups == [
        (
            -100100,
            1,
            {
                "inline_keyboard": [
                    [
                        {"text": "Refresh", "callback_data": "gw:live:refresh"},
                        {"text": "Stop", "callback_data": "gw:live:stop"},
                    ]
                ]
            },
        )
    ]
    live_view = state.get_live_view(-100100, 77)
    assert live_view is not None
    assert live_view.message_id == 1
    assert live_view.codex_thread_id == "thread-1"


def test_poll_telegram_once_ticks_live_view_and_edits_same_message(tmp_path) -> None:
    first_capture = tmp_path / "live-1.png"
    second_capture = tmp_path / "live-2.png"
    first_capture.write_bytes(b"\x89PNG\r\n\x1a\nfirst")
    second_capture.write_bytes(b"\x89PNG\r\n\x1a\nsecond")
    started_at = time.monotonic()
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_live_view(
        LiveViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
            started_at=started_at,
            next_refresh_at=0.0,
            last_capture_hash="old",
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="running",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    screenshot_provider = SequencedScreenshotProvider([first_capture, second_capture])
    daemon = GatewayDaemon(
        config=make_config(live_view_interval_seconds=0.0, live_view_timeout_seconds=300.0),
        state=state,
        telegram=telegram,
        codex=codex,
        screenshot_provider=screenshot_provider,
    )

    daemon.poll_telegram_once()

    assert telegram.edited_photo_messages == [
        (
            -100100,
            15,
            str(first_capture),
            "Live view · gateway-project / thread-1",
            {
                "inline_keyboard": [
                    [
                        {"text": "Refresh", "callback_data": "gw:live:refresh"},
                        {"text": "Stop", "callback_data": "gw:live:stop"},
                    ]
                ]
            },
        )
    ]


def test_poll_telegram_once_live_view_stop_callback_clears_state() -> None:
    started_at = time.monotonic()
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_live_view(
        LiveViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
            started_at=started_at,
            next_refresh_at=started_at + 3600.0,
            last_capture_hash="hash",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-live-stop",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:live:stop",
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
        config=make_config(live_view_timeout_seconds=3600.0),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.get_live_view(-100100, 77) is None
    assert telegram.edited_captions == [
        (
            -100100,
            15,
            "Live view · gateway-project / thread-1\nStopped.",
            {
                "inline_keyboard": [
                    [
                        {"text": "Start live", "callback_data": "gw:live:start"},
                    ]
                ]
            },
        )
    ]
    assert telegram.answered_callback_queries[-1] == ("cb-live-stop", "Stopped.")


def test_poll_telegram_once_live_view_callback_rejects_unknown_action() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-live-unknown",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:live:nope",
    )
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="idle", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-live-unknown", "Unknown live view action.")


def test_poll_telegram_once_live_view_callback_requires_binding() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-live-unbound",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:live:refresh",
    )
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="idle", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == (
        "cb-live-unbound",
        "This topic is not bound to any Codex thread.",
    )


def test_poll_telegram_once_live_view_start_callback_edits_existing_message(tmp_path) -> None:
    screenshot_path = tmp_path / "live.png"
    screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-live-start",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:live:start",
    )
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="running", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
        screenshot_provider=StaticScreenshotProvider(screenshot_path),
    )

    daemon.poll_telegram_once()

    assert telegram.edited_photo_messages == [
        (
            -100100,
            15,
            str(screenshot_path),
            "Live view · gateway-project / thread-1",
            {
                "inline_keyboard": [
                    [
                        {"text": "Refresh", "callback_data": "gw:live:refresh"},
                        {"text": "Stop", "callback_data": "gw:live:stop"},
                    ]
                ]
            },
        )
    ]
    assert telegram.answered_callback_queries[-1] == ("cb-live-start", "Live view started.")


def test_poll_telegram_once_live_view_refresh_callback_rejects_stale_message() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_live_view(
        LiveViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
            started_at=time.monotonic(),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-live-refresh-stale",
        chat_id=-100100,
        message_thread_id=77,
        message_id=16,
        from_user_id=111,
        data="gw:live:refresh",
    )
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="running", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-live-refresh-stale", "Live view is not active.")


def test_poll_telegram_once_live_view_refresh_callback_reports_capture_failure(tmp_path) -> None:
    missing_path = tmp_path / "missing.png"
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_live_view(
        LiveViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
            started_at=time.monotonic(),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-live-refresh-fail",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:live:refresh",
    )
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="running", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
        screenshot_provider=MissingFileScreenshotProvider(missing_path),
    )

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == (
        "cb-live-refresh-fail",
        "Live view failed: Screenshot file is missing.",
    )


def test_poll_telegram_once_sessions_dashboard_live_reports_capture_failure(tmp_path) -> None:
    missing_path = tmp_path / "missing.png"
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-dashboard-live",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:live:0:-100100:77",
    )
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="running", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
        screenshot_provider=MissingFileScreenshotProvider(missing_path),
    )

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == (
        "cb-dashboard-live",
        "Live view failed: Screenshot file is missing.",
    )


def test_poll_telegram_once_gateway_live_requires_binding() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway live",
    )
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="idle", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "This topic is not bound to any Codex thread.",
        None,
    )


def test_poll_telegram_once_gateway_live_reports_capture_failure(tmp_path) -> None:
    missing_path = tmp_path / "missing.png"
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway live",
    )
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="running", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
        screenshot_provider=MissingFileScreenshotProvider(missing_path),
    )

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "Failed to start live view: Screenshot file is missing.",
        None,
    )


def test_poll_telegram_once_tick_live_view_stops_when_binding_missing() -> None:
    state = DummyState()
    state.upsert_live_view(
        LiveViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
            started_at=time.monotonic(),
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="running", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert state.get_live_view(-100100, 77) is None
    assert telegram.edited_captions[-1][2] == "Live view · gateway-project / thread-1\nStopped."


def test_poll_telegram_once_tick_live_view_stops_when_binding_closed() -> None:
    state = DummyState()
    state.create_binding(make_binding(binding_status=CLOSED_BINDING_STATUS))
    state.upsert_live_view(
        LiveViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
            started_at=time.monotonic(),
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="running", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert state.get_live_view(-100100, 77) is None
    assert telegram.edited_captions[-1][2] == "Live view · gateway-project / thread-1\nTopic unavailable."


def test_poll_telegram_once_tick_live_view_stops_on_timeout() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_live_view(
        LiveViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
            started_at=time.monotonic() - 10.0,
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="running", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(
        config=make_config(live_view_timeout_seconds=1.0),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert state.get_live_view(-100100, 77) is None
    assert telegram.edited_captions[-1][2] == "Live view · gateway-project / thread-1\nTimed out."


def test_poll_telegram_once_tick_live_view_skips_unchanged_capture(tmp_path) -> None:
    capture_path = tmp_path / "same.png"
    capture_path.write_bytes(b"\x89PNG\r\n\x1a\nsame")
    capture_hash = capture_hash_for_path(capture_path)
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_live_view(
        LiveViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_id="/Users/kangmo/sacle/src/gateway-project",
            started_at=time.monotonic(),
            next_refresh_at=0.0,
            last_capture_hash=capture_hash,
        )
    )
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(thread_id="thread-1", title="thread-1", status="running", cwd="/Users/kangmo/sacle/src/gateway-project")
    )
    daemon = GatewayDaemon(
        config=make_config(live_view_interval_seconds=5.0),
        state=state,
        telegram=telegram,
        codex=codex,
        screenshot_provider=StaticScreenshotProvider(capture_path),
    )

    daemon.poll_telegram_once()

    assert telegram.edited_photo_messages == []
    live_view = state.get_live_view(-100100, 77)
    assert live_view is not None
    assert live_view.last_capture_hash == capture_hash


def test_poll_telegram_once_sessions_dashboard_screenshot_sends_photo(tmp_path) -> None:
    screenshot_path = tmp_path / "screenshot.png"
    screenshot_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway sessions",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    screenshot_provider = StaticScreenshotProvider(screenshot_path)
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
        screenshot_provider=screenshot_provider,
    )

    daemon.poll_telegram_once()
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-shot",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:sessions:screenshot:0:-100100:77",
    )

    daemon.poll_telegram_once()

    assert screenshot_provider.calls == [
        (
            "thread-1",
            "thread-1",
            "/Users/kangmo/sacle/src/gateway-project",
        )
    ]
    assert telegram.sent_photos == [
        (
            -100100,
            77,
            str(screenshot_path),
            "Screenshot · gateway-project / thread-1",
        )
    ]
    assert telegram.answered_callback_queries[-1] == (
        "cb-shot",
        "Sent screenshot.",
    )


def test_poll_telegram_once_gateway_send_opens_project_root_browser(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    (project_root / "docs").mkdir(parents=True)
    (project_root / "notes.txt").write_text("notes")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "Send file from `gateway-project`\n\nCurrent: `.`\nTap a folder to enter or a file to preview.",
        {
            "inline_keyboard": [
                [{"text": "📁 docs", "callback_data": "gw:send:enter:0"}],
                [{"text": "📄 notes.txt", "callback_data": "gw:send:preview:1"}],
                [
                    {"text": "Root", "callback_data": "gw:send:root"},
                    {"text": "Cancel", "callback_data": "gw:send:cancel"},
                ],
            ]
        },
    )
    assert state.get_send_view(-100100, 77) is not None


def test_poll_telegram_once_gateway_send_exact_path_sends_document(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    file_path = project_root / "notes.txt"
    file_path.write_text("notes")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send notes.txt",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1][2] == (
        "Send file from `gateway-project`\n\n"
        "Path: `notes.txt`\n"
        "Type: `text/plain`\n"
        f"Size: `{file_path.stat().st_size} B`\n\n"
        "Choose how to send this file."
    )

    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-send-doc",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:send:doc",
    )
    daemon.poll_telegram_once()

    assert Path(telegram.sent_documents[-1][2]).name == "notes.txt"
    assert telegram.sent_documents[-1][3] == "notes.txt"
    assert telegram.answered_callback_queries[-1] == ("cb-send-doc", "Sent as document.")
    assert state.get_send_view(-100100, 77) is None


def test_poll_telegram_once_gateway_send_browse_and_send_photo(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    image_path = project_root / "images" / "diagram.png"
    image_path.parent.mkdir(parents=True)
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-enter-images",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:send:enter:0",
    )
    daemon.poll_telegram_once()
    telegram.push_callback_query(
        update_id=3,
        callback_query_id="cb-preview-image",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:send:preview:0",
    )
    daemon.poll_telegram_once()
    telegram.push_callback_query(
        update_id=4,
        callback_query_id="cb-send-photo",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:send:photo",
    )
    daemon.poll_telegram_once()

    assert Path(telegram.sent_photos[-1][2]).name == "diagram.png"
    assert telegram.sent_photos[-1][3] == "images/diagram.png"
    assert telegram.answered_callback_queries[-1] == ("cb-send-photo", "Sent as photo.")


def test_poll_telegram_once_gateway_send_rejects_stale_send_view(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    (project_root / "notes.txt").write_text("notes")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-stale-send",
        chat_id=-100100,
        message_thread_id=77,
        message_id=999,
        from_user_id=111,
        data="gw:send:doc",
    )
    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-stale-send", "This send browser is stale.")


def test_poll_telegram_once_gateway_send_rejects_unknown_callback_payload(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    state.upsert_send_view(
        SendViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_root=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-send-unknown",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:send:broken:1",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-send-unknown", "Unknown send action.")


def test_poll_telegram_once_gateway_send_rejects_when_binding_no_longer_matches_view(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-2",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-2",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    state.upsert_send_view(
        SendViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_root=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-send-mismatch",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:send:cancel",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-2",
            title="thread-2",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-send-mismatch", "This send browser is stale.")
    assert state.get_send_view(-100100, 77) is None


def test_poll_telegram_once_gateway_send_cancel_clears_browser_state(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    state.upsert_send_view(
        SendViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_root=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-send-cancel",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:send:cancel",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.edited_reply_markups == [(-100100, 15, None)]
    assert telegram.answered_callback_queries[-1] == ("cb-send-cancel", "Cancelled.")
    assert state.get_send_view(-100100, 77) is None


def test_poll_telegram_once_gateway_send_root_reopens_project_root_listing(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    (project_root / "docs").mkdir(parents=True)
    (project_root / "docs" / "notes.txt").write_text("notes")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    state.upsert_send_view(
        SendViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_root=str(project_root),
            current_relative_path="docs",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-send-root",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:send:root",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.edited_messages[-1][2] == (
        "Send file from `gateway-project`\n\nCurrent: `.`\nTap a folder to enter or a file to preview."
    )
    assert telegram.answered_callback_queries[-1] == ("cb-send-root", None)
    assert state.get_send_view(-100100, 77).current_relative_path == "."


def test_poll_telegram_once_gateway_send_back_from_preview_restores_listing(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    (project_root / "docs").mkdir(parents=True)
    (project_root / "docs" / "notes.txt").write_text("notes")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    state.upsert_send_view(
        SendViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_root=str(project_root),
            current_relative_path="docs",
            selected_relative_path="docs/notes.txt",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-send-back-preview",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:send:back",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert "Current: `docs`" in telegram.edited_messages[-1][2]
    assert telegram.answered_callback_queries[-1] == ("cb-send-back-preview", None)
    assert state.get_send_view(-100100, 77).selected_relative_path is None


def test_poll_telegram_once_gateway_send_back_from_directory_goes_to_parent(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    (project_root / "docs").mkdir(parents=True)
    (project_root / "docs" / "notes.txt").write_text("notes")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    state.upsert_send_view(
        SendViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_root=str(project_root),
            current_relative_path="docs",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-send-back-dir",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:send:back",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.edited_messages[-1][2].startswith("Send file from `gateway-project`\n\nCurrent: `.`")
    assert telegram.answered_callback_queries[-1] == ("cb-send-back-dir", None)
    assert state.get_send_view(-100100, 77).current_relative_path == "."


def test_poll_telegram_once_gateway_send_page_callback_updates_listing(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    for index in range(8):
        (project_root / f"file-{index}.txt").write_text(str(index))
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    state.upsert_send_view(
        SendViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_root=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-send-page",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data="gw:send:page:1",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.edited_messages[-1][3] == {
        "inline_keyboard": [
            [{"text": "📄 file-6.txt", "callback_data": "gw:send:preview:0"}],
            [{"text": "📄 file-7.txt", "callback_data": "gw:send:preview:1"}],
            [{"text": "Prev", "callback_data": "gw:send:page:0"}],
            [
                {"text": "Root", "callback_data": "gw:send:root"},
                {"text": "Cancel", "callback_data": "gw:send:cancel"},
            ],
        ]
    }
    assert telegram.answered_callback_queries[-1] == ("cb-send-page", None)
    assert state.get_send_view(-100100, 77).page_index == 1


@pytest.mark.parametrize(
    ("callback_data", "selected_relative_path", "expected_text"),
    [
        ("gw:send:enter:9", None, "This send browser is stale."),
        ("gw:send:enter:1", None, "That entry is not a folder."),
        ("gw:send:preview:9", None, "This send browser is stale."),
        ("gw:send:doc", None, "This send browser is stale."),
        ("gw:send:photo", "notes.txt", "This file cannot be sent as a photo."),
    ],
)
def test_poll_telegram_once_gateway_send_rejects_invalid_selection_callbacks(
    tmp_path,
    callback_data: str,
    selected_relative_path: str | None,
    expected_text: str,
) -> None:
    project_root = tmp_path / "gateway-project"
    (project_root / "docs").mkdir(parents=True)
    (project_root / "docs" / "nested.txt").write_text("nested")
    (project_root / "notes.txt").write_text("notes")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    state.upsert_send_view(
        SendViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=15,
            codex_thread_id="thread-1",
            project_root=str(project_root),
            selected_relative_path=selected_relative_path,
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-send-invalid",
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        from_user_id=111,
        data=callback_data,
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-send-invalid", expected_text)


def test_poll_telegram_once_gateway_send_rejects_unbound_topic() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "This topic is not bound to any Codex thread.",
        None,
    )


def test_poll_telegram_once_gateway_send_rejects_mirror_topic_controls(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    state = DummyState()
    state.upsert_mirror_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (-100100, 77, _mirror_control_text(), None)


def test_poll_telegram_once_gateway_send_reports_missing_project_path() -> None:
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=None,
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=None,
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "This topic is bound, but the Codex project path is missing.",
        None,
    )


def test_poll_telegram_once_gateway_send_uses_thread_cwd_for_directory_queries(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    (project_root / "docs").mkdir(parents=True)
    (project_root / "docs" / "notes.txt").write_text("notes")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=None,
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send docs",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1][2].startswith("Send file from `gateway-project`\n\nCurrent: `docs`")
    assert state.get_send_view(-100100, 77).current_relative_path == "docs"


def test_poll_telegram_once_gateway_send_searches_when_query_is_not_a_safe_path(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    (project_root / "notes.txt").write_text("notes")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send ../secret",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()

    assert "Search: `../secret`" in telegram.sent_messages[-1][2]
    assert state.get_send_view(-100100, 77).query == "../secret"


def test_show_send_preview_requires_selected_path(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    daemon = GatewayDaemon(
        config=make_config(),
        state=DummyState(),
        telegram=DummyTelegramClient(),
        codex=DummyCodexBridge(
            CodexThread(
                thread_id="thread-1",
                title="thread-1",
                status="idle",
                cwd=str(project_root),
            )
        ),
    )

    with pytest.raises(ValueError, match="selected_relative_path is required"):
        daemon._show_send_preview(
            SendViewState(
                chat_id=-100100,
                message_thread_id=77,
                message_id=15,
                codex_thread_id="thread-1",
                project_root=str(project_root),
            )
        )


def test_poll_telegram_once_gateway_send_rejects_directory_preview_callback(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    (project_root / "docs").mkdir(parents=True)
    (project_root / "docs" / "notes.txt").write_text("notes")
    state = DummyState()
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.poll_telegram_once()
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-send-preview-dir",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:send:preview:0",
    )
    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-send-preview-dir", "That entry is not a file.")


def test_sessions_dashboard_entry_uses_status_icons_and_warnings_for_binding_state() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="closed-thread",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    deleted_thread = codex.create_thread(
        "/Users/kangmo/sacle/src/gateway-project",
        thread_name="deleted-thread",
    )
    approval_thread = codex.create_thread(
        "/Users/kangmo/sacle/src/gateway-project",
        thread_name="approval-thread",
    )
    running_thread = codex.create_thread(
        "/Users/kangmo/sacle/src/gateway-project",
        thread_name="running-thread",
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    closed_binding = Binding(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=71,
        topic_name="(gateway-project) closed-thread",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
        binding_status=CLOSED_BINDING_STATUS,
    )
    deleted_binding = Binding(
        codex_thread_id=deleted_thread.thread_id,
        chat_id=-100100,
        message_thread_id=72,
        topic_name="(gateway-project) deleted-thread",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
        binding_status=DELETED_BINDING_STATUS,
    )
    approval_binding = Binding(
        codex_thread_id=approval_thread.thread_id,
        chat_id=-100100,
        message_thread_id=73,
        topic_name="(gateway-project) approval-thread",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )
    running_binding = Binding(
        codex_thread_id=running_thread.thread_id,
        chat_id=-100100,
        message_thread_id=74,
        topic_name="(gateway-project) running-thread",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )
    unloaded_binding = Binding(
        codex_thread_id="thread-missing",
        chat_id=-100100,
        message_thread_id=75,
        topic_name="(gateway-project) missing-thread",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id=approval_thread.thread_id,
            chat_id=-100100,
            message_thread_id=73,
            turn_id="turn-approval",
            waiting_for_approval=True,
        )
    )
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id=running_thread.thread_id,
            chat_id=-100100,
            message_thread_id=74,
            turn_id="turn-running",
            waiting_for_approval=False,
        )
    )

    closed_entry = daemon._session_dashboard_entry_for_binding(closed_binding)
    deleted_entry = daemon._session_dashboard_entry_for_binding(deleted_binding)
    approval_entry = daemon._session_dashboard_entry_for_binding(approval_binding)
    running_entry = daemon._session_dashboard_entry_for_binding(running_binding)
    unloaded_entry = daemon._session_dashboard_entry_for_binding(unloaded_binding)

    assert (closed_entry.thread_status, closed_entry.status_icon, closed_entry.warning_text) == (
        "closed",
        "⚫",
        "Topic was closed in Telegram.",
    )
    assert (deleted_entry.thread_status, deleted_entry.status_icon, deleted_entry.warning_text) == (
        "deleted",
        "🔴",
        "Telegram topic is missing and can be recreated.",
    )
    assert (approval_entry.thread_status, approval_entry.status_icon, approval_entry.warning_text) == (
        "approval",
        "🟠",
        None,
    )
    assert (running_entry.thread_status, running_entry.status_icon, running_entry.warning_text) == (
        "running",
        "🟢",
        None,
    )
    assert (unloaded_entry.thread_status, unloaded_entry.status_icon, unloaded_entry.warning_text) == (
        "notLoaded",
        "⚪",
        "Codex thread is not loaded in the app.",
    )


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


def test_poll_telegram_once_learns_passthrough_commands_and_refreshes_menu() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/status",
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

    assert state.list_passthrough_commands() == ("status",)
    assert state.get_registered_command_menu_hash("chat:-100100") is not None
    assert telegram.registered_command_sets == [
        (
            (
                ("gateway", "Gateway control commands and status"),
                ("status", "Show Codex status in the bound thread"),
            ),
            {"type": "chat", "chat_id": -100100},
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


def test_poll_telegram_once_queues_document_prompt_for_bound_topic() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    telegram._updates.append(
        {
            "kind": "message",
            "update_id": 4,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 111,
            "text": (
                "I've uploaded a PDF to /tmp/project/.ccgram-uploads/design-spec.pdf. "
                "Please inspect or read it as needed."
            ),
            "local_image_paths": (),
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
            telegram_update_id=4,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text=(
                "I've uploaded a PDF to /tmp/project/.ccgram-uploads/design-spec.pdf. "
                "Please inspect or read it as needed."
            ),
            local_image_paths=(),
        )
    ]


def test_poll_telegram_once_replies_to_unsupported_media_without_queueing() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram._updates.append(
        {
            "kind": "unsupported_message",
            "update_id": 5,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 111,
            "notice": "⚠ Stickers are not supported yet. Use text, photos, documents, audio, or video.",
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

    assert state.list_pending_inbound() == []
    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "⚠ Stickers are not supported yet. Use text, photos, documents, audio, or video.",
            None,
        )
    ]


def test_poll_telegram_once_transcribes_voice_and_sends_confirmation(tmp_path) -> None:
    voice_path = tmp_path / ".ccgram-uploads" / "voice.ogg"
    voice_path.parent.mkdir(parents=True)
    voice_path.write_bytes(b"ogg-bytes")
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram._updates.append(
        {
            "kind": "voice_message",
            "update_id": 7,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 111,
            "file_path": str(voice_path),
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
    transcriber = StaticTranscriptionProvider("Please continue with the deployment.")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
        transcriber=transcriber,
    )

    daemon.poll_telegram_once()

    assert transcriber.calls == [str(voice_path)]
    assert telegram.sent_chat_actions == [(-100100, 77, "typing")]
    assert non_bubble_sent_messages(telegram) == [
        (
            -100100,
            77,
            "Voice transcription\n\nPlease continue with the deployment.",
            {
                "inline_keyboard": [
                    [{"text": "Send", "callback_data": "gw:voice:send"}],
                    [{"text": "Discard", "callback_data": "gw:voice:drop"}],
                ]
            },
        )
    ]
    assert state.get_voice_prompt_view(-100100, 77) == VoicePromptViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        codex_thread_id="thread-1",
        source_update_id=7,
        from_user_id=111,
        transcript_text="Please continue with the deployment.",
    )


def test_voice_callback_send_queues_transcript_for_bound_topic() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    state.upsert_voice_prompt_view(
        VoicePromptViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            codex_thread_id="thread-1",
            source_update_id=12,
            from_user_id=111,
            transcript_text="Please continue with the deployment.",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=13,
        callback_query_id="cb-voice-send",
        chat_id=-100100,
        message_thread_id=77,
        message_id=9,
        from_user_id=111,
        data="gw:voice:send",
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
            telegram_update_id=12,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Please continue with the deployment.",
            local_image_paths=(),
        )
    ]
    assert state.get_voice_prompt_view(-100100, 77) is None


def test_voice_callback_send_opens_project_picker_for_unbound_topic() -> None:
    state = DummyState()
    state.upsert_voice_prompt_view(
        VoicePromptViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            codex_thread_id="",
            source_update_id=12,
            from_user_id=111,
            transcript_text="Please continue with the deployment.",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=13,
        callback_query_id="cb-voice-send",
        chat_id=-100100,
        message_thread_id=77,
        message_id=9,
        from_user_id=111,
        data="gw:voice:send",
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
    assert topic_project is not None
    assert topic_project.pending_update_id == 12
    assert topic_project.pending_user_id == 111
    assert topic_project.pending_text == "Please continue with the deployment."
    assert state.get_voice_prompt_view(-100100, 77) is None
def test_poll_telegram_once_ignores_unsupported_media_from_unauthorized_user() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram._updates.append(
        {
            "kind": "unsupported_message",
            "update_id": 6,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 999,
            "notice": "⚠ Voice messages are not supported yet. Use text, photos, documents, audio, or video.",
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

    assert state.list_pending_inbound() == []
    assert telegram.sent_messages == []


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


def test_deliver_inbound_once_suppresses_typing_when_notification_mode_is_muted() -> None:
    state = DummyState()
    state.create_binding(replace(make_binding(), sync_mode="muted"))
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
            telegram_update_id=22,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Please continue quietly.",
        )
    )

    daemon.deliver_inbound_once()

    assert codex.started_turns == [
        StartedTurn(thread_id="thread-1", text="Please continue quietly."),
    ]
    assert telegram.sent_chat_actions == []
    assert state.get_pending_turn("thread-1") is not None


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

    assert non_bubble_sent_messages(telegram) == [
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


def test_sync_codex_once_suppresses_typing_for_approval_blocked_turn_when_errors_only() -> None:
    state = DummyState()
    state.create_binding(replace(make_binding(), sync_mode="errors_only"))
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

    assert telegram.sent_chat_actions == []
    assert state.get_pending_turn("thread-1") is not None


def test_sync_codex_once_reports_failed_turn_even_when_notification_mode_is_muted() -> None:
    state = DummyState()
    state.create_binding(replace(make_binding(), sync_mode="muted"))
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-11",
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
    codex.inspect_results[("thread-1", "turn-11")] = TurnResult(turn_id="turn-11", status="failed")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert non_bubble_sent_messages(telegram) == [
        (
            -100100,
            77,
            "Codex started processing your message, but the turn failed before a final answer was produced.",
            None,
        )
    ]
    assert state.get_pending_turn("thread-1") is None


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

    assert non_bubble_sent_messages(telegram) == [
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

    assert non_bubble_sent_messages(telegram) == [
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


def test_sync_codex_once_shows_interactive_prompt_widget_for_pending_approval() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-approval",
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
    codex.inspect_results[("thread-1", "turn-approval")] = TurnResult(
        turn_id="turn-approval",
        status="interrupted",
        waiting_for_approval=True,
    )
    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-approval",
            method="item/commandExecution/requestApproval",
            params={
                "threadId": "thread-1",
                "turnId": "turn-approval",
                "itemId": "item-1",
                "command": "pytest -q",
                "cwd": "/tmp/project",
            },
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert non_bubble_sent_messages(telegram)[-1][2].startswith("Command Approval")
    assert non_bubble_sent_messages(telegram)[-1][3] == {
        "inline_keyboard": [
            [{"text": "Approve Once", "callback_data": "gw:prompt:choose:prompt-approval:accept"}],
            [{"text": "Approve Session", "callback_data": "gw:prompt:choose:prompt-approval:acceptForSession"}],
            [{"text": "Decline", "callback_data": "gw:prompt:choose:prompt-approval:decline"}],
            [{"text": "Cancel Turn", "callback_data": "gw:prompt:choose:prompt-approval:cancel"}],
        ]
    }
    prompt_view = state.get_interactive_prompt_view(-100100, 77)
    assert prompt_view is not None
    assert prompt_view.prompt_id == "prompt-approval"


def test_poll_telegram_once_interactive_prompt_callback_submits_decision() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-approval",
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
    codex.inspect_results[("thread-1", "turn-approval")] = TurnResult(
        turn_id="turn-approval",
        status="interrupted",
        waiting_for_approval=True,
    )
    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-approval",
            method="item/fileChange/requestApproval",
            params={
                "threadId": "thread-1",
                "turnId": "turn-approval",
                "itemId": "item-2",
                "reason": "Update generated files.",
            },
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )
    daemon.sync_codex_once()

    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-prompt",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:prompt:choose:prompt-approval:accept",
    )

    daemon.poll_telegram_once()

    assert codex.interactive_responses == [("prompt-approval", {"decision": "accept"})]
    assert telegram.answered_callback_queries[-1] == ("cb-prompt", "Sent.")
    assert telegram.edited_messages[-1] == (
        -100100,
        1,
        "Sent your answer to Codex.\n\nFile Change Approval",
        None,
    )


def test_poll_telegram_once_text_during_approval_prompt_asks_user_to_use_buttons() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-approval",
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
    codex.inspect_results[("thread-1", "turn-approval")] = TurnResult(
        turn_id="turn-approval",
        status="interrupted",
        waiting_for_approval=True,
    )
    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-approval",
            method="item/commandExecution/requestApproval",
            params={"threadId": "thread-1", "turnId": "turn-approval", "itemId": "item-1", "command": "pytest -q"},
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)
    daemon.sync_codex_once()

    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="approve it",
    )

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "Please use the prompt buttons above for this question.",
        None,
    )
    assert codex.interactive_responses == []


def test_poll_telegram_once_text_answer_submits_interactive_question_instead_of_queueing_turn() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-question",
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
    codex.inspect_results[("thread-1", "turn-question")] = TurnResult(
        turn_id="turn-question",
        status="interrupted",
        waiting_for_approval=True,
    )
    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-question",
            method="item/tool/requestUserInput",
            params={
                "threadId": "thread-1",
                "turnId": "turn-question",
                "itemId": "item-3",
                "questions": [
                    {
                        "header": "Reason",
                        "id": "reason",
                        "question": "Why do you need this?",
                    }
                ],
            },
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )
    daemon.sync_codex_once()

    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="Need the production-safe path.",
    )

    daemon.poll_telegram_once()

    assert codex.interactive_responses == [
        (
            "prompt-question",
            {"answers": {"reason": {"answers": ["Need the production-safe path."]}}},
        )
    ]
    assert state.pending_inbound_count() == 0
    assert codex.started_turns == []


def test_poll_telegram_once_option_prompt_rejects_free_text_reply() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-question",
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
    codex.inspect_results[("thread-1", "turn-question")] = TurnResult(
        turn_id="turn-question",
        status="interrupted",
        waiting_for_approval=True,
    )
    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-question",
            method="item/tool/requestUserInput",
            params={
                "threadId": "thread-1",
                "turnId": "turn-question",
                "itemId": "item-3",
                "questions": [
                    {
                        "header": "Mode",
                        "id": "mode",
                        "question": "Choose a mode",
                        "options": [
                            {"label": "Fast", "description": "Optimize for speed"},
                            {"label": "Safe", "description": "Optimize for caution"},
                        ],
                    }
                ],
            },
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)
    daemon.sync_codex_once()

    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="Fast",
    )

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "Please use the prompt buttons above for this question.",
        None,
    )
    assert codex.interactive_responses == []
    assert codex.started_turns == []


def test_sync_codex_once_does_not_resend_identical_interactive_prompt() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-approval",
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
    codex.inspect_results[("thread-1", "turn-approval")] = TurnResult(
        turn_id="turn-approval",
        status="interrupted",
        waiting_for_approval=True,
    )
    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-approval",
            method="item/commandExecution/requestApproval",
            params={"threadId": "thread-1", "turnId": "turn-approval", "itemId": "item-1", "command": "pytest -q"},
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)

    daemon.sync_codex_once()
    daemon.sync_codex_once()

    assert non_bubble_sent_messages(telegram) == [
        (
            -100100,
            77,
            "Command Approval\n\nCommand: `pytest -q`",
            {
                "inline_keyboard": [
                    [{"text": "Approve Once", "callback_data": "gw:prompt:choose:prompt-approval:accept"}],
                    [{"text": "Approve Session", "callback_data": "gw:prompt:choose:prompt-approval:acceptForSession"}],
                    [{"text": "Decline", "callback_data": "gw:prompt:choose:prompt-approval:decline"}],
                    [{"text": "Cancel Turn", "callback_data": "gw:prompt:choose:prompt-approval:cancel"}],
                ]
            },
        )
    ]


def test_poll_telegram_once_interactive_prompt_callback_rejects_invalid_choice() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-approval",
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
    codex.inspect_results[("thread-1", "turn-approval")] = TurnResult(
        turn_id="turn-approval",
        status="interrupted",
        waiting_for_approval=True,
    )
    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-approval",
            method="item/fileChange/requestApproval",
            params={"threadId": "thread-1", "turnId": "turn-approval", "itemId": "item-1", "reason": "Update files"},
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)
    daemon.sync_codex_once()

    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-invalid-choice",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:prompt:choose:prompt-approval:not-a-real-choice",
    )

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == (
        "cb-invalid-choice",
        "That prompt choice is no longer available.",
    )


def test_poll_telegram_once_interactive_text_reply_rejects_image_payload() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-question",
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
    codex.inspect_results[("thread-1", "turn-question")] = TurnResult(
        turn_id="turn-question",
        status="interrupted",
        waiting_for_approval=True,
    )
    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-question",
            method="item/tool/requestUserInput",
            params={
                "threadId": "thread-1",
                "turnId": "turn-question",
                "itemId": "item-2",
                "questions": [{"header": "Reason", "id": "reason", "question": "Why?"}],
            },
        )
    )
    daemon = GatewayDaemon(config=make_config(), state=state, telegram=telegram, codex=codex)
    daemon.sync_codex_once()

    telegram.push_photo_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="see attached",
        local_image_path="/tmp/example.png",
    )

    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (-100100, 77, "This prompt expects a text reply.", None)
    assert codex.interactive_responses == []


def test_sync_codex_once_creates_and_updates_status_bubble_in_place() -> None:
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

    daemon.sync_codex_once()

    assert state.get_status_bubble_view(-100100, 77) == StatusBubbleViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        codex_thread_id="thread-1",
    )
    assert telegram.sent_messages == [
        (
            -100100,
            77,
            "Topic status\n\n"
            "Project: `gateway-project`\n"
            "Thread: `thread-1`\n"
            "State: `ready`\n"
            "Queued: `0`\n"
            "Latest: No assistant reply yet.",
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
        )
    ]

    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-1",
        )
    )
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="in_progress")

    daemon.sync_codex_once()

    assert telegram.edited_messages[-1] == (
        -100100,
        1,
        "Topic status\n\n"
        "Project: `gateway-project`\n"
        "Thread: `thread-1`\n"
        "State: `running`\n"
        "Queued: `0`\n"
        "Latest: No assistant reply yet.",
        {
            "inline_keyboard": [
                [{"text": "⏳ Working", "callback_data": "gw:resp:noop"}],
                [
                    {"text": "⏹ Stop", "callback_data": "gw:remote:interrupt:turn-1"},
                    {"text": "▶ Continue", "callback_data": "gw:remote:continue:turn-1"},
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


def test_poll_telegram_once_status_bubble_callback_reuses_response_actions() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_status_bubble_view(
        StatusBubbleViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=7,
            codex_thread_id="thread-1",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-status-bubble",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:resp:status",
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
            "Topic status\n\n"
            "Project: `gateway-project`\n"
            "Thread title: `thread-1`\n"
            "Thread id: `thread-1`\n"
            "Topic id: `77`\n"
            "Notification mode: `all`\n"
            "Codex status: `idle`",
            None,
        )
    ]


def test_poll_telegram_once_remote_interrupt_callback_interrupts_turn_and_updates_status_bubble() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.record_topic_history(-100100, 77, text="Please keep going.")
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
    bubble = state.get_status_bubble_view(-100100, 77)
    assert bubble is not None
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-stop",
        chat_id=-100100,
        message_thread_id=77,
        message_id=bubble.message_id,
        from_user_id=111,
        data="gw:remote:interrupt:turn-1",
    )

    daemon.poll_telegram_once()

    assert codex.interrupted_turns == [("thread-1", "turn-1")]
    assert state.get_pending_turn("thread-1") is None
    assert telegram.answered_callback_queries[-1] == ("cb-remote-stop", "Stopped.")
    assert telegram.edited_messages[-1] == (
        -100100,
        bubble.message_id,
        "Topic status\n\n"
        "Project: `gateway-project`\n"
        "Thread: `thread-1`\n"
        "State: `failed`\n"
        "Queued: `0`\n"
        "Latest: No assistant reply yet.",
        {
            "inline_keyboard": [
                [{"text": "⚠ Turn Failed", "callback_data": "gw:resp:noop"}],
                [{"text": "↑ Please keep going.", "callback_data": "gw:resp:recall:0"}],
                [{"text": "↻ Retry Last", "callback_data": "gw:remote:retry:0"}],
                [
                    {"text": "↺ New", "callback_data": "gw:resp:new"},
                    {"text": "📁 Project", "callback_data": "gw:resp:project"},
                    {"text": "📍 Status", "callback_data": "gw:resp:status"},
                    {"text": "🔄 Sync", "callback_data": "gw:resp:sync"},
                ],
            ]
        },
    )


def test_poll_telegram_once_remote_continue_callback_steers_current_turn() -> None:
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
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-continue",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:continue:turn-1",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
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

    assert codex.steered_turns == [
        (
            "turn-1",
            StartedTurn(
                thread_id="thread-1",
                text="Continue.",
            ),
        )
    ]
    assert telegram.answered_callback_queries[-1] == ("cb-remote-continue", "Steered.")


def test_poll_telegram_once_remote_prompt_callback_reuses_interactive_prompt_response() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.upsert_interactive_prompt_view(
        InteractivePromptViewState(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            codex_thread_id="thread-1",
            prompt_id="prompt-approval",
            prompt_kind="command_approval",
        )
    )
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-prompt",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:prompt:prompt-approval:accept",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-approval",
            method="item/commandExecution/requestApproval",
            params={
                "threadId": "thread-1",
                "turnId": "turn-approval",
                "itemId": "item-1",
                "command": "pytest -q",
                "cwd": "/tmp/project",
            },
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.poll_telegram_once()

    assert codex.interactive_responses == [("prompt-approval", {"decision": "accept"})]
    assert telegram.answered_callback_queries[-1] == ("cb-remote-prompt", "Sent.")
    assert telegram.edited_messages[-1] == (
        -100100,
        9,
        "Sent your answer to Codex.\n\nCommand Approval",
        None,
    )


def test_poll_telegram_once_remote_retry_callback_requeues_latest_history_entry() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.record_topic_history(-100100, 77, text="Retry me.")
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-retry",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:retry:0",
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
            telegram_update_id=1,
            chat_id=-100100,
            message_thread_id=77,
            from_user_id=111,
            codex_thread_id="thread-1",
            text="Retry me.",
            local_image_paths=(),
        )
    ]
    assert telegram.answered_callback_queries[-1] == ("cb-remote-retry", "Queued.")


def test_status_bubble_remote_actions_skip_approval_prompt_without_options() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["InteractivePrompt"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.queue_interactive_prompt(
        interactive.InteractivePrompt(
            prompt_id="prompt-empty",
            thread_id="thread-1",
            turn_id="turn-approval",
            kind="command_approval",
            title="Command Approval",
            body="",
            options=(),
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=DummyTelegramClient(),
        codex=codex,
    )

    assert daemon._status_bubble_remote_action_rows(
        binding=binding,
        pending_turn=PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-approval",
            waiting_for_approval=True,
        ),
        turn_result=TurnResult(
            turn_id="turn-approval",
            status="interrupted",
            waiting_for_approval=True,
        ),
        history=[],
    ) == ()


def test_poll_telegram_once_remote_action_callback_rejects_unknown_payload() -> None:
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-unknown",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:broken",
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=DummyState(),
        telegram=telegram,
        codex=DummyCodexBridge(
            CodexThread(
                thread_id="thread-1",
                title="thread-1",
                status="idle",
                cwd="/Users/kangmo/sacle/src/gateway-project",
            )
        ),
    )

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-remote-unknown", "Unknown remote action.")


def test_poll_telegram_once_remote_action_callback_rejects_unbound_topic() -> None:
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-unbound",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:interrupt:turn-1",
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=DummyState(),
        telegram=telegram,
        codex=DummyCodexBridge(
            CodexThread(
                thread_id="thread-1",
                title="thread-1",
                status="idle",
                cwd="/Users/kangmo/sacle/src/gateway-project",
            )
        ),
    )

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-remote-unbound", "This topic is no longer bound.")


def test_poll_telegram_once_remote_action_callback_rejects_closed_topic() -> None:
    state = DummyState()
    state.create_binding(replace(make_binding(), binding_status=CLOSED_BINDING_STATUS))
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-closed",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:interrupt:turn-1",
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=DummyCodexBridge(
            CodexThread(
                thread_id="thread-1",
                title="thread-1",
                status="idle",
                cwd="/Users/kangmo/sacle/src/gateway-project",
            )
        ),
    )

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-remote-closed", "This topic needs restore first.")


def test_poll_telegram_once_remote_interrupt_callback_rejects_stale_turn() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-stop-stale",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:interrupt:turn-1",
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=DummyCodexBridge(
            CodexThread(
                thread_id="thread-1",
                title="thread-1",
                status="busy",
                cwd="/Users/kangmo/sacle/src/gateway-project",
            )
        ),
    )

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == ("cb-remote-stop-stale", "This control is stale.")


def test_poll_telegram_once_remote_continue_callback_rejects_waiting_approval_and_errors() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
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
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-continue-approval",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:continue:turn-1",
    )
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
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

    assert telegram.answered_callback_queries[-1] == (
        "cb-remote-continue-approval",
        "Use the approval buttons first.",
    )

    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-2",
        )
    )
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-remote-continue-error",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:continue:turn-2",
    )
    codex.next_steer_error = RuntimeError("cannot steer")

    daemon.poll_telegram_once()

    assert telegram.answered_callback_queries[-1] == (
        "cb-remote-continue-error",
        "This Codex turn cannot be steered. The message stays queued.",
    )


def test_poll_telegram_once_remote_prompt_callback_handles_missing_invalid_and_direct_response() -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-prompt-missing",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:prompt:prompt-missing:accept",
    )
    daemon.poll_telegram_once()
    assert telegram.answered_callback_queries[-1] == (
        "cb-remote-prompt-missing",
        "This approval request is no longer pending.",
    )

    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-bad",
            method="item/commandExecution/requestApproval",
            params={
                "threadId": "thread-1",
                "turnId": "turn-approval",
                "itemId": "item-1",
                "command": "pytest -q",
            },
        )
    )
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-remote-prompt-invalid",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:prompt:prompt-bad:not-a-choice",
    )
    daemon.poll_telegram_once()
    assert telegram.answered_callback_queries[-1] == (
        "cb-remote-prompt-invalid",
        "Unknown approval choice.",
    )

    codex.queue_interactive_prompt(
        interactive.normalize_interactive_request(
            prompt_id="prompt-direct",
            method="item/commandExecution/requestApproval",
            params={
                "threadId": "thread-1",
                "turnId": "turn-approval",
                "itemId": "item-1",
                "command": "pytest -q",
            },
        )
    )
    telegram.push_callback_query(
        update_id=3,
        callback_query_id="cb-remote-prompt-direct",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:prompt:prompt-direct:accept",
    )
    daemon.poll_telegram_once()

    assert codex.interactive_responses[-1] == ("prompt-direct", {"decision": "accept"})
    assert telegram.answered_callback_queries[-1] == ("cb-remote-prompt-direct", "Sent.")


def test_poll_telegram_once_remote_retry_callback_rejects_busy_invalid_and_missing_history() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    state.upsert_pending_turn(
        PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-1",
        )
    )
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-remote-retry-busy",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:retry:0",
    )
    daemon.poll_telegram_once()
    assert telegram.answered_callback_queries[-1] == (
        "cb-remote-retry-busy",
        "Codex is still answering right now.",
    )

    state.delete_pending_turn("thread-1")
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-remote-retry-invalid",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:retry:not-a-number",
    )
    daemon.poll_telegram_once()
    assert telegram.answered_callback_queries[-1] == ("cb-remote-retry-invalid", "Invalid retry item.")

    telegram.push_callback_query(
        update_id=3,
        callback_query_id="cb-remote-retry-missing",
        chat_id=-100100,
        message_thread_id=77,
        message_id=7,
        from_user_id=111,
        data="gw:remote:retry:0",
    )
    daemon.poll_telegram_once()
    assert telegram.answered_callback_queries[-1] == (
        "cb-remote-retry-missing",
        "That message is no longer available.",
    )


def test_sync_codex_once_edits_same_tool_batch_message_as_commands_accumulate() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:tool-batch:0",
            thread_id="thread-1",
            kind="tool_batch",
            text="⚡ 1 command\n• pwd  ⏳ running",
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
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="in_progress")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()
    codex.replace_event(
        "thread-1",
        "thread-1:turn-1:tool-batch:0",
        "⚡ 2 commands\n• pwd  ✅ /tmp/project\n• pytest -q  ⏳ running",
    )
    daemon.sync_codex_once()

    assert non_bubble_sent_messages(telegram) == [
        (-100100, 77, "⚡ 1 command\n• pwd  ⏳ running", None)
    ]
    assert non_bubble_edited_messages(telegram) == [
        (-100100, 1, "⚡ 2 commands\n• pwd  ✅ /tmp/project\n• pytest -q  ⏳ running", None)
    ]


def test_sync_codex_once_emits_terminal_summary_for_tool_only_turns() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:tool-batch:0",
            thread_id="thread-1",
            kind="tool_batch",
            text="⚡ 1 command\n• pytest -q  ❌ AssertionError: boom",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:completion-summary",
            thread_id="thread-1",
            kind="completion_summary",
            text="⚠ Turn failed — pytest -q: AssertionError: boom",
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
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="failed")
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert non_bubble_sent_messages(telegram) == [
        (-100100, 77, "⚡ 1 command\n• pytest -q  ❌ AssertionError: boom", None),
        (-100100, 77, "⚠ Turn failed — pytest -q: AssertionError: boom", None),
    ]
    assert telegram.edited_reply_markups[-1] == (
        -100100,
        2,
        {
            "inline_keyboard": [
                [{"text": "⚠ Turn Failed", "callback_data": "gw:resp:noop"}],
            ]
        },
    )


def test_sync_codex_once_sends_artifacts_once_per_event(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    photo_path = project_root / "artifacts" / "diagram.png"
    document_path = project_root / "reports" / "summary.txt"
    photo_path.parent.mkdir(parents=True)
    document_path.parent.mkdir(parents=True)
    photo_path.write_bytes(b"png-bytes")
    document_path.write_text("done\n")
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="I generated two artifacts.",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1:artifact:photo",
            thread_id="thread-1",
            kind="artifact_photo",
            text="Artifact: artifacts/diagram.png",
            file_path=str(photo_path),
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1:artifact:document",
            thread_id="thread-1",
            kind="artifact_document",
            text="Artifact: reports/summary.txt",
            file_path=str(document_path),
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

    assert non_bubble_sent_messages(telegram) == [
        (-100100, 77, "I generated two artifacts.", None)
    ]
    assert telegram.sent_photos == [
        (-100100, 77, str(photo_path), "Artifact: artifacts/diagram.png")
    ]
    assert telegram.sent_documents == [
        (-100100, 77, str(document_path), "Artifact: reports/summary.txt")
    ]


def test_sync_codex_once_skips_artifact_when_file_is_missing(tmp_path) -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(tmp_path / "gateway-project"),
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1:artifact:photo",
            thread_id="thread-1",
            kind="artifact_photo",
            text="Artifact: artifacts/missing.png",
            file_path=str(tmp_path / "gateway-project" / "artifacts" / "missing.png"),
        )
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert telegram.sent_photos == []
    assert state.has_seen_event("thread-1", "thread-1:turn-1:item-1:artifact:photo") is False


def test_sync_codex_once_marks_binding_deleted_when_artifact_send_hits_missing_topic(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    photo_path = project_root / "artifacts" / "diagram.png"
    photo_path.parent.mkdir(parents=True)
    photo_path.write_bytes(b"png-bytes")
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1:artifact:photo",
            thread_id="thread-1",
            kind="artifact_photo",
            text="Artifact: artifacts/diagram.png",
            file_path=str(photo_path),
        )
    )
    telegram.send_photo_file = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        TelegramApiError("message thread not found")
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    assert state.get_binding_by_thread("thread-1").binding_status == DELETED_BINDING_STATUS


def test_sync_codex_once_reraises_unexpected_artifact_send_failures(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    document_path = project_root / "reports" / "summary.txt"
    document_path.parent.mkdir(parents=True)
    document_path.write_text("done\n")
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    telegram = DummyTelegramClient()
    codex = DummyCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd=str(project_root),
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1:artifact:document",
            thread_id="thread-1",
            kind="artifact_document",
            text="Artifact: reports/summary.txt",
            file_path=str(document_path),
        )
    )
    telegram.send_document_file = lambda *args, **kwargs: (_ for _ in ()).throw(  # type: ignore[method-assign]
        RuntimeError("upload failed")
    )
    daemon = GatewayDaemon(
        config=make_config(),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    with pytest.raises(RuntimeError, match="upload failed"):
        daemon.sync_codex_once()


def test_poll_telegram_once_answers_inline_query_with_echo_and_matching_commands() -> None:
    state = DummyState()
    state.remember_passthrough_command("status")
    telegram = DummyTelegramClient()
    telegram.push_inline_query_update(
        update_id=1,
        inline_query_id="inline-1",
        from_user_id=111,
        query="sta",
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

    assert len(telegram.answered_inline_queries) == 1
    inline_query_id, results, cache_time, is_personal = telegram.answered_inline_queries[0]
    assert inline_query_id == "inline-1"
    assert cache_time == 0
    assert is_personal is True
    inserted_texts = [result["input_message_content"]["message_text"] for result in results]
    assert inserted_texts[0] == "sta"
    assert "/gateway status" in inserted_texts
    assert "/status" in inserted_texts


def test_poll_telegram_once_ignores_unauthorized_inline_query() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_inline_query_update(
        update_id=1,
        inline_query_id="inline-1",
        from_user_id=999,
        query="sta",
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

    assert telegram.answered_inline_queries == []


def test_poll_telegram_once_gateway_recall_renders_recent_topic_history() -> None:
    state = DummyState()
    binding = make_binding()
    state.create_binding(binding)
    state.record_topic_history(-100100, 77, text="Please continue with the refactor.")
    state.record_topic_history(
        -100100,
        77,
        text="Please inspect the screenshots.",
        local_image_paths=("/tmp/one.png", "/tmp/two.png"),
    )
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway recall",
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

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "Recent topic messages\n\nTap a text-only entry to edit it inline before sending, or use the image entry buttons to replay the full message with attachments.",
        {
            "inline_keyboard": [
                [
                    {
                        "text": "↑ Please inspect the screenshots. [2 images]",
                        "callback_data": "gw:resp:recall:0",
                    }
                ],
                [
                    {
                        "text": "↑ Please continue with the refactor.",
                        "switch_inline_query_current_chat": "Please continue with the refactor.",
                    }
                ],
                [{"text": "Close", "callback_data": "gw:recall:dismiss"}],
            ]
        },
    )


def test_poll_telegram_once_gateway_recall_reports_empty_history() -> None:
    state = DummyState()
    state.create_binding(make_binding())
    telegram = DummyTelegramClient()
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway recall",
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

    assert telegram.sent_messages[-1] == (-100100, 77, "No recent topic messages yet.", None)


def test_recall_dismiss_callback_clears_reply_markup() -> None:
    state = DummyState()
    telegram = DummyTelegramClient()
    telegram.push_callback_query(
        update_id=1,
        callback_query_id="cb-recall-dismiss",
        chat_id=-100100,
        message_thread_id=77,
        message_id=42,
        from_user_id=111,
        data="gw:recall:dismiss",
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

    assert telegram.edited_reply_markups == [(-100100, 42, None)]
    assert telegram.answered_callback_queries == [("cb-recall-dismiss", "Dismissed.")]
