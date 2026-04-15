from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.daemon import GatewayDaemon
from codex_telegram_gateway.history_command import CALLBACK_HISTORY_PREFIX
from codex_telegram_gateway.models import (
    Binding,
    CodexEvent,
    CodexHistoryEntry,
    CodexProject,
    CodexThread,
    StartedTurn,
    TurnResult,
)
from codex_telegram_gateway.state import SqliteGatewayState


class FakeTelegramClient:
    def __init__(self) -> None:
        self._updates: list[dict[str, object]] = []
        self._next_message_id = 1
        self.sent_messages: list[tuple[int, int, str, dict[str, object] | None]] = []
        self.edited_messages: list[tuple[int, int, str, dict[str, object] | None]] = []
        self.answered_callback_queries: list[tuple[str, str | None]] = []

    def create_forum_topic(self, chat_id: int, name: str) -> int:
        del chat_id, name
        raise AssertionError("Not used in history flow test")

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
        del chat_id, message_thread_id, name

    def close_forum_topic(self, chat_id: int, message_thread_id: int) -> None:
        del chat_id, message_thread_id

    def probe_topic(self, chat_id: int, message_thread_id: int) -> bool:
        del chat_id, message_thread_id
        return True


class FakeCodexBridge:
    def __init__(self, thread: CodexThread, history_entries: list[CodexHistoryEntry]) -> None:
        self.current_thread_id = thread.thread_id
        self._thread = thread
        self._history_entries = history_entries

    def get_current_thread_id(self) -> str:
        return self.current_thread_id

    def list_loaded_threads(self) -> list[CodexThread]:
        return [self._thread]

    def list_loaded_projects(self) -> list[CodexProject]:
        return [CodexProject(project_id=self._thread.cwd, project_name="gateway-project")]

    def list_all_threads(self) -> list[CodexThread]:
        return [self._thread]

    def list_workspace_threads(self, cwd: str) -> list[CodexThread]:
        del cwd
        return [self._thread]

    def read_thread(self, thread_id: str) -> CodexThread:
        assert thread_id == self._thread.thread_id
        return self._thread

    def list_events(self, thread_id: str) -> list[CodexEvent]:
        del thread_id
        return []

    def list_history_entries(self, thread_id: str) -> list[CodexHistoryEntry]:
        assert thread_id == self._thread.thread_id
        return list(self._history_entries)

    def create_thread(self, project_id: str, thread_name: str | None = None) -> CodexThread:
        del project_id, thread_name
        raise AssertionError("Not used in history flow test")

    def rename_thread(self, thread_id: str, thread_name: str) -> CodexThread:
        del thread_id, thread_name
        raise AssertionError("Not used in history flow test")

    def ensure_project_visible(self, project_id: str) -> None:
        del project_id

    def start_turn(self, started_turn: StartedTurn, on_progress=None) -> TurnResult:
        del started_turn, on_progress
        raise AssertionError("Not used in history flow test")

    def steer_turn(self, started_turn: StartedTurn, expected_turn_id: str, on_progress=None) -> TurnResult:
        del started_turn, expected_turn_id, on_progress
        raise AssertionError("Not used in history flow test")

    def inspect_turn(self, thread_id: str, turn_id: str) -> TurnResult:
        del thread_id, turn_id
        raise AssertionError("Not used in history flow test")


def test_history_callback_paging_survives_daemon_restart(tmp_path) -> None:
    database_path = tmp_path / "gateway.db"
    thread = CodexThread(
        thread_id="thread-1",
        title="thread-1",
        status="idle",
        cwd="/Users/kangmo/sacle/src/gateway-project",
    )
    history_entries = [
        CodexHistoryEntry(
            entry_id=f"entry-{index}",
            kind="assistant",
            text=f"history entry {index} " + ("x" * 500),
            timestamp="2026-04-15T10:00:00Z",
        )
        for index in range(12)
    ]
    config = GatewayConfig(
        telegram_bot_token="test-token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(thread, history_entries)

    state = SqliteGatewayState(database_path)
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) thread-1",
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
            "text": "/gateway history",
        }
    )
    first_daemon = GatewayDaemon(config=config, state=state, telegram=telegram, codex=codex)
    first_daemon.poll_telegram_once()

    first_view = state.get_history_view(-100100, 77)
    assert first_view is not None
    assert telegram.sent_messages[0][3] == {
        "inline_keyboard": [
            [
                {
                    "text": "◀ Older",
                    "callback_data": f"{CALLBACK_HISTORY_PREFIX}{first_view.page_index - 1}:thread-1",
                },
                {"text": f"{first_view.page_index + 1}/{first_view.page_index + 1}", "callback_data": "tp:noop"},
            ]
        ]
    }

    restarted_state = SqliteGatewayState(database_path)
    telegram.push_update(
        {
            "kind": "callback_query",
            "update_id": 2,
            "callback_query_id": "cb-history",
            "chat_id": -100100,
            "message_thread_id": 77,
            "message_id": 1,
            "from_user_id": 111,
            "data": f"{CALLBACK_HISTORY_PREFIX}{first_view.page_index - 1}:thread-1",
        }
    )
    second_daemon = GatewayDaemon(
        config=config,
        state=restarted_state,
        telegram=telegram,
        codex=codex,
    )
    second_daemon.poll_telegram_once()

    assert telegram.edited_messages == [
        (
            -100100,
            1,
            telegram.edited_messages[0][2],
            {
                "inline_keyboard": [
                    [
                        {
                            "text": "◀ Older",
                            "callback_data": f"{CALLBACK_HISTORY_PREFIX}{first_view.page_index - 2}:thread-1",
                        },
                        {"text": f"{first_view.page_index}/{first_view.page_index + 1}", "callback_data": "tp:noop"},
                        {
                            "text": "Newer ▶",
                            "callback_data": f"{CALLBACK_HISTORY_PREFIX}{first_view.page_index}:thread-1",
                        },
                    ]
                ]
            },
        )
    ]
    assert telegram.answered_callback_queries[-1] == ("cb-history", "Page updated.")
