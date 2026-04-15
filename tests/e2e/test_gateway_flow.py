from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.daemon import GatewayDaemon
from codex_telegram_gateway.models import CodexEvent, CodexProject, CodexThread, StartedTurn, TurnResult
from codex_telegram_gateway.service import GatewayService
from codex_telegram_gateway.state import SqliteGatewayState


class FakeTelegramClient:
    """In-memory Telegram bot stub used by the end-to-end contract."""

    def __init__(self) -> None:
        self._next_topic_id = 1
        self._updates: list[dict[str, object]] = []
        self._next_message_id = 1
        self.created_topics: list[tuple[int, str]] = []
        self.sent_messages: list[tuple[int, int, str, dict[str, object] | None]] = []
        self.sent_chat_actions: list[tuple[int, int, str]] = []
        self.edited_messages: list[tuple[int, int, str, dict[str, object] | None]] = []

    def create_forum_topic(self, chat_id: int, name: str) -> int:
        topic_id = self._next_topic_id
        self._next_topic_id += 1
        self.created_topics.append((chat_id, name))
        return topic_id

    def push_update(
        self,
        *,
        update_id: int,
        chat_id: int,
        message_thread_id: int,
        from_user_id: int,
        text: str,
    ) -> None:
        self._updates.append(
            {
                "kind": "message",
                "update_id": update_id,
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "from_user_id": from_user_id,
                "text": text,
            }
        )

    def push_photo_update(
        self,
        *,
        update_id: int,
        chat_id: int,
        message_thread_id: int,
        from_user_id: int,
        text: str,
        local_image_path: str,
    ) -> None:
        self._updates.append(
            {
                "kind": "message",
                "update_id": update_id,
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "from_user_id": from_user_id,
                "text": text,
                "local_image_paths": (local_image_path,),
            }
        )

    def get_updates(self, offset: int | None = None) -> list[dict[str, object]]:
        if offset is None:
            return list(self._updates)
        return [update for update in self._updates if int(update["update_id"]) >= offset]

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
        self.sent_chat_actions.append((chat_id, message_thread_id, action))

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        del callback_query_id, text

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

    def probe_topic(self, chat_id: int, message_thread_id: int) -> bool:
        del chat_id, message_thread_id
        return True

    def clear_sent_messages(self) -> None:
        self.sent_messages.clear()


class FakeCodexBridge:
    """In-memory Codex bridge stub used by the end-to-end contract."""

    def __init__(self, thread: CodexThread) -> None:
        self.current_thread_id = thread.thread_id
        self._threads = {thread.thread_id: thread}
        self._events: dict[str, list[CodexEvent]] = {thread.thread_id: []}
        self.started_turns: list[StartedTurn] = []
        self.ensured_projects: list[str] = []
        self.inspect_results: dict[tuple[str, str], TurnResult] = {}

    def get_current_thread_id(self) -> str:
        return self.current_thread_id

    def read_thread(self, thread_id: str) -> CodexThread:
        return self._threads[thread_id]

    def list_loaded_threads(self) -> list[CodexThread]:
        return list(self._threads.values())

    def list_loaded_projects(self) -> list[CodexProject]:
        return [
            CodexProject(
                project_id="/Users/kangmo/sacle/src/gateway-project",
                project_name="gateway-project",
            )
        ]

    def list_all_threads(self) -> list[CodexThread]:
        return list(self._threads.values())

    def list_workspace_threads(self, cwd: str) -> list[CodexThread]:
        del cwd
        return list(self._threads.values())

    def list_events(self, thread_id: str) -> list[CodexEvent]:
        return list(self._events[thread_id])

    def append_event(self, event: CodexEvent) -> None:
        self._events[event.thread_id].append(event)

    def replace_event(self, thread_id: str, event_id: str, text: str) -> None:
        self._events[thread_id] = [
            CodexEvent(
                event_id=event.event_id,
                thread_id=event.thread_id,
                kind=event.kind,
                text=text if event.event_id == event_id else event.text,
            )
            for event in self._events[thread_id]
        ]

    def create_thread(self, project_id: str, thread_name: str | None = None) -> CodexThread:
        del project_id, thread_name
        raise AssertionError("create_thread is not used in this end-to-end flow")

    def rename_thread(self, thread_id: str, thread_name: str) -> CodexThread:
        self._threads[thread_id] = CodexThread(
            thread_id=thread_id,
            title=thread_name,
            status=self._threads[thread_id].status,
            cwd=self._threads[thread_id].cwd,
        )
        return self._threads[thread_id]

    def ensure_project_visible(self, project_id: str) -> None:
        if project_id not in self.ensured_projects:
            self.ensured_projects.append(project_id)

    def start_turn(self, started_turn: StartedTurn, on_progress=None) -> TurnResult:
        self.started_turns.append(started_turn)
        if on_progress is not None:
            on_progress()
        result = TurnResult(turn_id="turn-1", status="in_progress")
        self.inspect_results[(started_turn.thread_id, result.turn_id)] = result
        return result

    def inspect_turn(self, thread_id: str, turn_id: str) -> TurnResult:
        return self.inspect_results[(thread_id, turn_id)]

    def set_thread_status(self, thread_id: str, status: str) -> None:
        self._threads[thread_id] = CodexThread(
            thread_id=thread_id,
            title=self._threads[thread_id].title,
            status=status,
            cwd=self._threads[thread_id].cwd,
        )


def test_gateway_flow_end_to_end(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Sync topic replies",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    config = GatewayConfig(
        telegram_bot_token="test-token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )

    service = GatewayService(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )
    daemon = GatewayDaemon(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )

    binding = service.link_current_thread()
    assert binding.codex_thread_id == "thread-1"
    assert binding.chat_id == -100100
    assert binding.topic_name == "(gateway-project) Sync topic replies"
    assert telegram.created_topics == [(-100100, "(gateway-project) Sync topic replies")]
    telegram.clear_sent_messages()

    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="Completed the refactor.",
        )
    )
    daemon.sync_codex_once()
    daemon.sync_codex_once()

    assert telegram.sent_messages == [
        (-100100, binding.message_thread_id, "Completed the refactor.", None),
    ]

    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=binding.message_thread_id,
        from_user_id=999,
        text="Ignore me.",
    )
    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=binding.message_thread_id,
        from_user_id=111,
        text="Please continue.",
    )

    daemon.poll_telegram_once()
    assert state.pending_inbound_count() == 1

    codex.set_thread_status("thread-1", "idle")
    daemon.deliver_inbound_once()

    assert codex.started_turns == [
        StartedTurn(thread_id="thread-1", text="Please continue."),
    ]
    assert state.pending_inbound_count() == 0
    assert state.get_pending_turn("thread-1") is not None


def test_gateway_flow_end_to_end_with_photo_message(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Inspect screenshots",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    config = GatewayConfig(
        telegram_bot_token="test-token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )

    service = GatewayService(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )
    daemon = GatewayDaemon(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )

    binding = service.link_current_thread()
    image_path = tmp_path / "input-photo.jpg"
    image_path.write_bytes(b"jpeg-bytes")
    telegram.push_photo_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=binding.message_thread_id,
        from_user_id=111,
        text="Please inspect the screenshot.",
        local_image_path=str(image_path),
    )

    daemon.poll_telegram_once()
    daemon.deliver_inbound_once()

    assert codex.started_turns == [
        StartedTurn(
            thread_id="thread-1",
            text="Please inspect the screenshot.",
            local_image_paths=(str(image_path),),
        )
    ]
    assert state.get_pending_turn("thread-1") is not None
