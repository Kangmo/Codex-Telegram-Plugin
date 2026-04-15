from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.daemon import GatewayDaemon
from codex_telegram_gateway.models import (
    Binding,
    CodexEvent,
    CodexProject,
    CodexThread,
    StartedTurn,
    TurnResult,
)
from codex_telegram_gateway.resume_command import CALLBACK_RESUME_PICK_PREFIX
from codex_telegram_gateway.state import SqliteGatewayState


class FakeTelegramClient:
    def __init__(self) -> None:
        self._updates: list[dict[str, object]] = []
        self._next_message_id = 1
        self.created_topics: list[tuple[int, str]] = []
        self.sent_messages: list[tuple[int, int, str, dict[str, object] | None]] = []
        self.edited_messages: list[tuple[int, int, str, dict[str, object] | None]] = []
        self.edited_topics: list[tuple[int, int, str]] = []
        self.answered_callback_queries: list[tuple[str, str | None]] = []

    def create_forum_topic(self, chat_id: int, name: str) -> int:
        topic_id = self._next_message_id
        self._next_message_id += 1
        self.created_topics.append((chat_id, name))
        return topic_id

    def get_chat(self, chat_id: int) -> dict[str, object]:
        return {"id": chat_id, "title": "dummy-chat", "type": "supergroup"}

    def get_updates(self, offset: int | None = None) -> list[dict[str, object]]:
        if offset is None:
            return list(self._updates)
        return [update for update in self._updates if int(update["update_id"]) >= offset]

    def push_update(self, update: dict[str, object]) -> None:
        self._updates.append(update)

    def send_message(
        self,
        chat_id: int,
        message_thread_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> int:
        message_id = self._next_message_id
        self._next_message_id += 1
        self.sent_messages.append((chat_id, message_thread_id, text, reply_markup))
        return message_id

    def send_chat_action(self, chat_id: int, message_thread_id: int, action: str) -> None:
        del chat_id, message_thread_id, action

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        self.answered_callback_queries.append((callback_query_id, text))

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict[str, object] | None,
    ) -> None:
        del chat_id, message_id, reply_markup

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> None:
        self.edited_messages.append((chat_id, message_id, text, reply_markup))

    def edit_forum_topic(self, chat_id: int, message_thread_id: int, name: str) -> None:
        self.edited_topics.append((chat_id, message_thread_id, name))

    def close_forum_topic(self, chat_id: int, message_thread_id: int) -> None:
        del chat_id, message_thread_id

    def probe_topic(self, chat_id: int, message_thread_id: int) -> bool:
        del chat_id, message_thread_id
        return True


class FakeCodexBridge:
    def __init__(self, threads: list[CodexThread]) -> None:
        self.current_thread_id = threads[0].thread_id
        self._threads = {thread.thread_id: thread for thread in threads}
        self._events = {thread.thread_id: [] for thread in threads}

    def get_current_thread_id(self) -> str:
        return self.current_thread_id

    def read_thread(self, thread_id: str) -> CodexThread:
        return self._threads[thread_id]

    def list_loaded_threads(self) -> list[CodexThread]:
        return [thread for thread in self._threads.values() if thread.status != "notLoaded"]

    def list_loaded_projects(self) -> list[CodexProject]:
        return [
            CodexProject(project_id="/Users/kangmo/sacle/src/gateway-project", project_name="gateway-project")
        ]

    def list_all_threads(self) -> list[CodexThread]:
        return list(self._threads.values())

    def list_workspace_threads(self, cwd: str) -> list[CodexThread]:
        return [thread for thread in self._threads.values() if thread.cwd == cwd]

    def list_events(self, thread_id: str) -> list[CodexEvent]:
        return list(self._events[thread_id])

    def list_history_entries(self, thread_id: str):
        del thread_id
        return []

    def list_resumable_threads(
        self,
        project_id: str,
        *,
        exclude_thread_id: str | None = None,
        limit: int = 12,
    ) -> list[CodexThread]:
        threads = [
            thread
            for thread in self._threads.values()
            if thread.cwd == project_id and thread.thread_id != exclude_thread_id
        ]
        return threads[:limit]

    def create_thread(self, project_id: str, thread_name: str | None = None) -> CodexThread:
        del project_id, thread_name
        raise AssertionError("Not used in resume flow test")

    def resume_thread(self, thread_id: str) -> CodexThread:
        thread = self._threads[thread_id]
        self._threads[thread_id] = CodexThread(
            thread_id=thread.thread_id,
            title=thread.title,
            status="idle",
            cwd=thread.cwd,
        )
        return self._threads[thread_id]

    def rename_thread(self, thread_id: str, thread_name: str) -> CodexThread:
        self._threads[thread_id] = CodexThread(
            thread_id=thread_id,
            title=thread_name,
            status=self._threads[thread_id].status,
            cwd=self._threads[thread_id].cwd,
        )
        return self._threads[thread_id]

    def ensure_project_visible(self, project_id: str) -> None:
        del project_id

    def start_turn(self, started_turn: StartedTurn, on_progress=None) -> TurnResult:
        del started_turn, on_progress
        raise AssertionError("Not used in resume flow test")

    def steer_turn(self, started_turn: StartedTurn, expected_turn_id: str, on_progress=None) -> TurnResult:
        del started_turn, expected_turn_id, on_progress
        raise AssertionError("Not used in resume flow test")

    def inspect_turn(self, thread_id: str, turn_id: str) -> TurnResult:
        del thread_id, turn_id
        raise AssertionError("Not used in resume flow test")

    def append_event(self, event: CodexEvent) -> None:
        self._events[event.thread_id].append(event)


def test_resume_after_restart_rebinds_non_loaded_thread_without_replaying_old_output(tmp_path) -> None:
    database_path = tmp_path / "gateway.db"
    config = GatewayConfig(
        telegram_bot_token="test-token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        [
            CodexThread(
                thread_id="thread-1",
                title="current thread",
                status="idle",
                cwd="/Users/kangmo/sacle/src/gateway-project",
            ),
            CodexThread(
                thread_id="thread-2",
                title="older thread",
                status="notLoaded",
                cwd="/Users/kangmo/sacle/src/gateway-project",
            ),
        ]
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-2:old-event",
            thread_id="thread-2",
            kind="assistant_message",
            text="old reply",
        )
    )

    state = SqliteGatewayState(database_path)
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) current thread",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )

    telegram.push_update(
        {
            "kind": "message",
            "update_id": 1,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 111,
            "text": "/gateway resume",
        }
    )
    first_daemon = GatewayDaemon(config=config, state=state, telegram=telegram, codex=codex)
    first_daemon.poll_telegram_once()

    restarted_state = SqliteGatewayState(database_path)
    telegram.push_update(
        {
            "kind": "callback_query",
            "update_id": 2,
            "callback_query_id": "cb-resume",
            "chat_id": -100100,
            "message_thread_id": 77,
            "message_id": 1,
            "from_user_id": 111,
            "data": f"{CALLBACK_RESUME_PICK_PREFIX}thread-2",
        }
    )
    second_daemon = GatewayDaemon(config=config, state=restarted_state, telegram=telegram, codex=codex)
    second_daemon.poll_telegram_once()

    assert restarted_state.get_binding_by_topic(-100100, 77).codex_thread_id == "thread-2"
    assert restarted_state.has_seen_event("thread-2", "thread-2:old-event") is True

    codex.append_event(
        CodexEvent(
            event_id="thread-2:new-event",
            thread_id="thread-2",
            kind="assistant_message",
            text="fresh reply",
        )
    )
    second_daemon.sync_codex_once()

    assert telegram.edited_topics[:1] == [(-100100, 77, "(gateway-project) older thread")]
    assert telegram.created_topics == [(-100100, "(gateway-project) current thread")]
    assert telegram.edited_messages == [
        (
            -100100,
            1,
            "Resumed this topic into `older thread`.\nThread id: `thread-2`",
            None,
        )
    ]
    assert telegram.sent_messages[-1] == (-100100, 77, "fresh reply", None)
