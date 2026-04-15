from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.commands_catalog import register_bot_commands_if_changed
from codex_telegram_gateway.daemon import GatewayDaemon
from codex_telegram_gateway.interactive_bridge import InteractivePrompt
from codex_telegram_gateway.models import (
    Binding,
    CLOSED_BINDING_STATUS,
    CodexEvent,
    CodexHistoryEntry,
    CodexProject,
    CodexThread,
    StartedTurn,
    TurnResult,
)
from codex_telegram_gateway.recovery import CALLBACK_RESTORE_CONTINUE
from codex_telegram_gateway.service import GatewayService
from codex_telegram_gateway.state import SqliteGatewayState
from codex_telegram_gateway.toolbar import CALLBACK_TOOLBAR_PREFIX


class StaticTranscriptionProvider:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, audio_path):
        del audio_path
        return __import__("codex_telegram_gateway.voice_ingest", fromlist=["TranscriptionResult"]).TranscriptionResult(
            text=self.text,
            language="en",
        )


class FakeTelegramClient:
    """In-memory Telegram bot stub used by the end-to-end contract."""

    def __init__(self) -> None:
        self._next_topic_id = 1
        self._updates: list[dict[str, object]] = []
        self._next_message_id = 1
        self._deleted_message_ids: set[int] = set()
        self._live_message_ids: set[int] = set()
        self.created_topics: list[tuple[int, str]] = []
        self.sent_messages: list[tuple[int, int, str, dict[str, object] | None]] = []
        self.sent_documents: list[tuple[int, int, str, str | None]] = []
        self.sent_photos: list[tuple[int, int, str, str | None]] = []
        self.sent_chat_actions: list[tuple[int, int, str]] = []
        self.edited_messages: list[tuple[int, int, str, dict[str, object] | None]] = []
        self.answered_inline_queries: list[tuple[str, list[dict[str, object]], int, bool]] = []
        self.registered_command_sets: list[tuple[tuple[tuple[str, str], ...], dict[str, object] | None]] = []

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

    def push_callback_query(
        self,
        *,
        update_id: int,
        callback_query_id: str,
        chat_id: int,
        message_thread_id: int,
        message_id: int,
        from_user_id: int,
        data: str,
    ) -> None:
        self._updates.append(
            {
                "kind": "callback_query",
                "update_id": update_id,
                "callback_query_id": callback_query_id,
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "message_id": message_id,
                "from_user_id": from_user_id,
                "data": data,
            }
        )

    def push_inline_query(
        self,
        *,
        update_id: int,
        inline_query_id: str,
        from_user_id: int,
        query: str,
    ) -> None:
        self._updates.append(
            {
                "kind": "inline_query",
                "update_id": update_id,
                "inline_query_id": inline_query_id,
                "from_user_id": from_user_id,
                "query": query,
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
        self._live_message_ids.add(message_id)
        self.sent_messages.append((chat_id, message_thread_id, text, reply_markup))
        return message_id

    def send_chat_action(self, chat_id: int, message_thread_id: int, action: str) -> None:
        self.sent_chat_actions.append((chat_id, message_thread_id, action))

    def send_document_file(
        self,
        chat_id: int,
        message_thread_id: int,
        file_path,
        *,
        caption: str | None = None,
    ) -> int:
        message_id = self._next_message_id
        self._next_message_id += 1
        self._live_message_ids.add(message_id)
        self.sent_documents.append((chat_id, message_thread_id, str(file_path), caption))
        return message_id

    def send_photo_file(
        self,
        chat_id: int,
        message_thread_id: int,
        file_path,
        *,
        caption: str | None = None,
    ) -> int:
        message_id = self._next_message_id
        self._next_message_id += 1
        self._live_message_ids.add(message_id)
        self.sent_photos.append((chat_id, message_thread_id, str(file_path), caption))
        return message_id

    def set_my_commands(
        self,
        commands: list[tuple[str, str]],
        scope: dict[str, object] | None = None,
    ) -> None:
        self.registered_command_sets.append((tuple(commands), scope))

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        del callback_query_id, text

    def answer_inline_query(
        self,
        inline_query_id: str,
        results: list[dict[str, object]],
        *,
        cache_time: int = 0,
        is_personal: bool = True,
    ) -> None:
        self.answered_inline_queries.append((inline_query_id, results, cache_time, is_personal))

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
        if message_id in self._deleted_message_ids:
            raise RuntimeError("message to edit not found")
        self.edited_messages.append((chat_id, message_id, text, reply_markup))

    def edit_forum_topic(self, chat_id: int, message_thread_id: int, name: str) -> None:
        del chat_id, message_thread_id, name

    def delete_message_locally(self, message_id: int) -> None:
        self._deleted_message_ids.add(message_id)
        self._live_message_ids.discard(message_id)

    def probe_topic(self, chat_id: int, message_thread_id: int) -> bool:
        del chat_id, message_thread_id
        return True

    def clear_sent_messages(self) -> None:
        self.sent_messages.clear()


def non_bubble_sent_messages(
    telegram: FakeTelegramClient,
) -> list[tuple[int, int, str, dict[str, object] | None]]:
    return [
        message
        for message in telegram.sent_messages
        if not message[2].startswith("Topic status\n\n")
    ]


def non_bubble_edited_messages(
    telegram: FakeTelegramClient,
) -> list[tuple[int, int, str, dict[str, object] | None]]:
    return [
        message
        for message in telegram.edited_messages
        if not message[2].startswith("Topic status\n\n")
    ]


def test_gateway_flow_toolbar_override_persists_across_restart(tmp_path) -> None:
    toolbar_config_path = tmp_path / "toolbar.toml"
    toolbar_config_path.write_text(
        "\n".join(
            [
                '[actions.status]',
                'emoji = "📍"',
                'text = "Status"',
                'type = "gateway_command"',
                'payload = "status"',
                "",
                "[actions.dismiss]",
                'emoji = "✖"',
                'text = "Close"',
                'type = "builtin"',
                'payload = "dismiss"',
                "",
                "[layout]",
                'style = "emoji_text"',
                'buttons = [["status", "dismiss"]]',
                "",
                '[topics."-100100:77"]',
                'style = "text"',
                'buttons = [["status"], ["dismiss"]]',
            ]
        )
    )
    config = GatewayConfig(
        telegram_bot_token="token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
        state_database_path=tmp_path / "gateway.db",
        toolbar_config_path=toolbar_config_path,
    )
    state = SqliteGatewayState(config.state_database_path)
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
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="thread-1",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    first_daemon = GatewayDaemon(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )

    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway toolbar",
    )
    first_daemon.poll_telegram_once()

    assert non_bubble_sent_messages(telegram) == [
        (
            -100100,
            77,
            "Topic toolbar\n\nProject: `gateway-project`\nThread id: `thread-1`",
            {
                "inline_keyboard": [
                    [{"text": "Status", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}status"}],
                    [{"text": "Close", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}dismiss"}],
                ]
            },
        )
    ]

    reopened_state = SqliteGatewayState(config.state_database_path)
    toolbar_view = reopened_state.get_toolbar_view(-100100, 77)
    assert toolbar_view is not None
    assert toolbar_view.message_id == 1

    second_daemon = GatewayDaemon(
        config=config,
        state=reopened_state,
        telegram=telegram,
        codex=codex,
    )
    telegram.clear_sent_messages()
    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway toolbar",
    )
    second_daemon.poll_telegram_once()

    assert non_bubble_sent_messages(telegram) == []
    assert non_bubble_edited_messages(telegram)[-1] == (
        -100100,
        1,
        "Topic toolbar\n\nProject: `gateway-project`\nThread id: `thread-1`",
        {
            "inline_keyboard": [
                [{"text": "Status", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}status"}],
                [{"text": "Close", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}dismiss"}],
            ]
        },
    )


class FakeCodexBridge:
    """In-memory Codex bridge stub used by the end-to-end contract."""

    def __init__(self, thread: CodexThread) -> None:
        self.current_thread_id = thread.thread_id
        self._threads = {thread.thread_id: thread}
        self._events: dict[str, list[CodexEvent]] = {thread.thread_id: []}
        self._history_entries: dict[str, list[CodexHistoryEntry]] = {thread.thread_id: []}
        self._interactive_prompts: dict[str, InteractivePrompt] = {}
        self.started_turns: list[StartedTurn] = []
        self.interactive_responses: list[tuple[str, dict[str, object]]] = []
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

    def list_history_entries(self, thread_id: str) -> list[CodexHistoryEntry]:
        return list(self._history_entries[thread_id])

    def list_pending_prompts(self, thread_id: str | None = None) -> list[InteractivePrompt]:
        prompts = list(self._interactive_prompts.values())
        if thread_id is None:
            return prompts
        return [prompt for prompt in prompts if prompt.thread_id == thread_id]

    def append_event(self, event: CodexEvent) -> None:
        self._events[event.thread_id].append(event)

    def queue_interactive_prompt(self, prompt: InteractivePrompt | None) -> None:
        if prompt is None:
            return
        self._interactive_prompts[prompt.prompt_id] = prompt

    def respond_interactive_prompt(self, prompt_id: str, payload: dict[str, object]) -> None:
        self.interactive_responses.append((prompt_id, payload))
        self._interactive_prompts.pop(prompt_id, None)

    def clear_pending_prompts(self, thread_id: str) -> None:
        self._interactive_prompts = {
            prompt_id: prompt
            for prompt_id, prompt in self._interactive_prompts.items()
            if prompt.thread_id != thread_id
        }

    def replace_event(self, thread_id: str, event_id: str, text: str) -> None:
        self._events[thread_id] = [
            CodexEvent(
                event_id=event.event_id,
                thread_id=event.thread_id,
                kind=event.kind,
                text=text if event.event_id == event_id else event.text,
                file_path=event.file_path,
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

    assert non_bubble_sent_messages(telegram) == [
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


def test_gateway_flow_end_to_end_with_document_prompt(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Inspect files",
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
    prompt_text = (
        "I've uploaded a PDF to /tmp/project/.ccgram-uploads/design-spec.pdf. "
        "Please inspect or read it as needed.\n\n"
        "User note: Please review this draft."
    )
    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=binding.message_thread_id,
        from_user_id=111,
        text=prompt_text,
    )

    daemon.poll_telegram_once()
    daemon.deliver_inbound_once()

    assert codex.started_turns == [
        StartedTurn(
            thread_id="thread-1",
            text=prompt_text,
            local_image_paths=(),
        )
    ]
    assert state.get_pending_turn("thread-1") is not None


def test_gateway_unbind_flow_returns_topic_to_project_picker(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Investigate gateway cleanup",
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
    telegram.clear_sent_messages()

    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=binding.message_thread_id,
        from_user_id=111,
        text="/gateway unbind",
    )
    daemon.poll_telegram_once()

    assert state.get_binding_by_topic(-100100, binding.message_thread_id) is None
    assert state.get_topic_project(-100100, binding.message_thread_id) is not None
    assert telegram.sent_messages[-1][2].startswith("✂ Unbound this topic from Codex thread.")

    telegram.push_update(
        update_id=2,
        chat_id=-100100,
        message_thread_id=binding.message_thread_id,
        from_user_id=111,
        text="Bind this somewhere else.",
    )
    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1][2].startswith("Select Codex Project")
    assert state.get_topic_project(-100100, binding.message_thread_id) is not None


def test_gateway_restore_continue_survives_restart_and_routes_next_message(tmp_path) -> None:
    database_path = tmp_path / "gateway.db"
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Recover closed topic",
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

    state = SqliteGatewayState(database_path)
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) Recover closed topic",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
            binding_status=CLOSED_BINDING_STATUS,
        )
    )

    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway restore",
    )
    first_daemon = GatewayDaemon(config=config, state=state, telegram=telegram, codex=codex)
    first_daemon.poll_telegram_once()

    restarted_state = SqliteGatewayState(database_path)
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-restore",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data=CALLBACK_RESTORE_CONTINUE,
    )
    second_daemon = GatewayDaemon(config=config, state=restarted_state, telegram=telegram, codex=codex)
    second_daemon.poll_telegram_once()

    assert restarted_state.get_binding_by_thread("thread-1").binding_status == "active"
    assert restarted_state.get_restore_view(-100100, 77) is None

    telegram.push_update(
        update_id=3,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="Please continue.",
    )
    second_daemon.poll_telegram_once()
    second_daemon.deliver_inbound_once()

    assert codex.started_turns == [StartedTurn(thread_id="thread-1", text="Please continue.")]


def test_verbose_mode_persists_across_restart_and_suppresses_typing(tmp_path) -> None:
    database_path = tmp_path / "gateway.db"
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Quiet topic",
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
    state = SqliteGatewayState(database_path)
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) Quiet topic",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )

    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway verbose",
    )
    first_daemon = GatewayDaemon(config=config, state=state, telegram=telegram, codex=codex)
    first_daemon.poll_telegram_once()

    restarted_state = SqliteGatewayState(database_path)
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-verbose-muted",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:verbose:set:muted",
    )
    second_daemon = GatewayDaemon(config=config, state=restarted_state, telegram=telegram, codex=codex)
    second_daemon.poll_telegram_once()

    assert restarted_state.get_binding_by_thread("thread-1").sync_mode == "muted"

    telegram.push_update(
        update_id=3,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="Please continue quietly.",
    )
    second_daemon.poll_telegram_once()
    second_daemon.deliver_inbound_once()

    assert codex.started_turns == [StartedTurn(thread_id="thread-1", text="Please continue quietly.")]
    assert telegram.sent_chat_actions == []


def test_command_menu_sync_persists_observed_passthrough_commands_across_restart(tmp_path) -> None:
    database_path = tmp_path / "gateway.db"
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Menu sync",
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
    state = SqliteGatewayState(database_path)
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) Menu sync",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )

    register_bot_commands_if_changed(telegram=telegram, state=state, config=config)
    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/status",
    )
    first_daemon = GatewayDaemon(config=config, state=state, telegram=telegram, codex=codex)
    first_daemon.poll_telegram_once()

    restarted_state = SqliteGatewayState(database_path)
    restarted_telegram = FakeTelegramClient()

    assert register_bot_commands_if_changed(telegram=restarted_telegram, state=restarted_state, config=config) is False
    assert restarted_state.list_passthrough_commands() == ("status",)
    assert telegram.registered_command_sets == [
        (
            (("gateway", "Gateway control commands and status"),),
            {"type": "chat", "chat_id": -100100},
        ),
        (
            (
                ("gateway", "Gateway control commands and status"),
                ("status", "Show Codex status in the bound thread"),
            ),
            {"type": "chat", "chat_id": -100100},
        ),
    ]
    assert restarted_telegram.registered_command_sets == []


def test_sessions_dashboard_refresh_updates_live_thread_metadata(tmp_path) -> None:
    database_path = tmp_path / "gateway.db"
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Dashboard thread",
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
    state = SqliteGatewayState(database_path)
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) Dashboard thread",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(config=config, state=state, telegram=telegram, codex=codex)

    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway bindings",
    )
    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (
        -100100,
        77,
        "Gateway sessions\n"
        "Page 1/1 • 1 binding\n\n"
        "1. 🟢 `(gateway-project) Dashboard thread`\n"
        "project `gateway-project` • thread `Dashboard thread`\n"
        "topic `77` • id `thread-1`\n"
        "status `idle` • notify `all`",
        {
            "inline_keyboard": [
                [
                    {"text": "↻", "callback_data": "gw:sessions:refresh:0:-100100:77"},
                    {"text": "➕", "callback_data": "gw:sessions:new:0:-100100:77"},
                    {"text": "✂", "callback_data": "gw:sessions:unbind:0:-100100:77"},
                    {"text": "📸", "callback_data": "gw:sessions:screenshot:0:-100100:77"},
                    {"text": "♻", "callback_data": "gw:sessions:restore:0:-100100:77"},
                ],
                [
                    {"text": "Refresh", "callback_data": "gw:sessions:refresh:0"},
                    {"text": "Dismiss", "callback_data": "gw:sessions:dismiss"},
                ],
            ]
        },
    )

    codex.rename_thread("thread-1", "Renamed live thread")
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-dashboard-refresh",
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
        "1. 🟢 `(gateway-project) Dashboard thread`\n"
        "project `gateway-project` • thread `Renamed live thread`\n"
        "topic `77` • id `thread-1`\n"
        "status `idle` • notify `all`",
        {
            "inline_keyboard": [
                [
                    {"text": "↻", "callback_data": "gw:sessions:refresh:0:-100100:77"},
                    {"text": "➕", "callback_data": "gw:sessions:new:0:-100100:77"},
                    {"text": "✂", "callback_data": "gw:sessions:unbind:0:-100100:77"},
                    {"text": "📸", "callback_data": "gw:sessions:screenshot:0:-100100:77"},
                    {"text": "♻", "callback_data": "gw:sessions:restore:0:-100100:77"},
                ],
                [
                    {"text": "Refresh", "callback_data": "gw:sessions:refresh:0"},
                    {"text": "Dismiss", "callback_data": "gw:sessions:dismiss"},
                ],
            ]
        },
    )


def test_send_flow_end_to_end_sends_project_file_to_telegram(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    file_path = project_root / "notes.txt"
    file_path.write_text("notes")
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Send flow",
            status="idle",
            cwd=str(project_root),
        )
    )
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) Send flow",
            sync_mode="assistant_plus_alerts",
            project_id=str(project_root),
        )
    )
    daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="test-token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            sync_mode="assistant_plus_alerts",
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        text="/gateway send notes.txt",
    )
    daemon.poll_telegram_once()

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

    assert telegram.sent_documents == [
        (-100100, 77, str(file_path), "notes.txt"),
    ]


def test_interactive_prompt_callback_expires_after_restart(tmp_path) -> None:
    interactive = __import__("codex_telegram_gateway.interactive_bridge", fromlist=["normalize_interactive_request"])

    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Approval flow",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) Approval flow",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    state.upsert_pending_turn(
        __import__("codex_telegram_gateway.models", fromlist=["PendingTurn"]).PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-approval",
            waiting_for_approval=True,
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
        config=GatewayConfig(
            telegram_bot_token="test-token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            sync_mode="assistant_plus_alerts",
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )
    daemon.sync_codex_once()

    restarted_telegram = FakeTelegramClient()
    restarted_codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Approval flow",
            status="busy",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    restarted_codex.inspect_results[("thread-1", "turn-approval")] = TurnResult(
        turn_id="turn-approval",
        status="interrupted",
        waiting_for_approval=True,
    )
    restarted_daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="test-token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            sync_mode="assistant_plus_alerts",
        ),
        state=SqliteGatewayState(tmp_path / "gateway.db"),
        telegram=restarted_telegram,
        codex=restarted_codex,
    )

    restarted_telegram.push_callback_query(
        update_id=10,
        callback_query_id="cb-expired",
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        from_user_id=111,
        data="gw:prompt:choose:prompt-approval:accept",
    )

    restarted_daemon.poll_telegram_once()

    assert restarted_telegram.edited_messages == [
        (
            -100100,
            1,
            "This prompt expired after the gateway restarted. Continue it from Codex App.",
            None,
        )
    ]


def test_status_bubble_recreated_after_message_deleted(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Status bubble",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    state.create_binding(
        Binding(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            topic_name="(gateway-project) Status bubble",
            sync_mode="assistant_plus_alerts",
            project_id="/Users/kangmo/sacle/src/gateway-project",
        )
    )
    daemon = GatewayDaemon(
        config=GatewayConfig(
            telegram_bot_token="test-token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            sync_mode="assistant_plus_alerts",
        ),
        state=state,
        telegram=telegram,
        codex=codex,
    )

    daemon.sync_codex_once()

    initial_bubble = state.get_status_bubble_view(-100100, 77)
    assert initial_bubble is not None
    assert initial_bubble.message_id == 1

    telegram.delete_message_locally(1)
    state.upsert_pending_turn(
        __import__("codex_telegram_gateway.models", fromlist=["PendingTurn"]).PendingTurn(
            codex_thread_id="thread-1",
            chat_id=-100100,
            message_thread_id=77,
            turn_id="turn-1",
        )
    )
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="in_progress")

    daemon.sync_codex_once()

    recreated_bubble = state.get_status_bubble_view(-100100, 77)
    assert recreated_bubble is not None
    assert recreated_bubble.message_id == 2
    assert telegram.sent_messages[-1][2].startswith("Topic status\n\nProject: `gateway-project`")


def test_gateway_flow_batches_tool_progress_and_sends_one_terminal_summary(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Batch tool progress",
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
    service = GatewayService(config=config, state=state, telegram=telegram, codex=codex)
    binding = service.link_current_thread()
    daemon = GatewayDaemon(config=config, state=state, telegram=telegram, codex=codex)

    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=binding.message_thread_id,
        from_user_id=111,
        text="Please continue.",
    )
    daemon.poll_telegram_once()
    daemon.deliver_inbound_once()

    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:tool-batch:0",
            thread_id="thread-1",
            kind="tool_batch",
            text="⚡ 1 command\n• pwd  ⏳ running",
        )
    )
    daemon.sync_codex_once()

    codex.replace_event(
        "thread-1",
        "thread-1:turn-1:tool-batch:0",
        "⚡ 2 commands\n• pwd  ✅ /tmp/project\n• pytest -q  ⏳ running",
    )
    daemon.sync_codex_once()

    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:completion-summary",
            thread_id="thread-1",
            kind="completion_summary",
            text="✓ Done — pytest -q: 3 passed in 0.80s",
        )
    )
    codex.inspect_results[("thread-1", "turn-1")] = TurnResult(turn_id="turn-1", status="completed")
    daemon.sync_codex_once()

    assert non_bubble_sent_messages(telegram) == [
        (-100100, binding.message_thread_id, "⚡ 1 command\n• pwd  ⏳ running", None),
        (-100100, binding.message_thread_id, "✓ Done — pytest -q: 3 passed in 0.80s", None),
    ]
    assert non_bubble_edited_messages(telegram)[-1] == (
        -100100,
        1,
        "⚡ 2 commands\n• pwd  ✅ /tmp/project\n• pytest -q  ⏳ running",
        None,
    )


def test_gateway_flow_sends_artifact_events_back_to_telegram(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    project_root = tmp_path / "gateway-project"
    artifact_path = project_root / "artifacts" / "diagram.png"
    artifact_path.parent.mkdir(parents=True)
    artifact_path.write_bytes(b"png-bytes")
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Artifact flow",
            status="idle",
            cwd=str(project_root),
        )
    )
    config = GatewayConfig(
        telegram_bot_token="test-token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
    )
    service = GatewayService(config=config, state=state, telegram=telegram, codex=codex)
    binding = service.link_current_thread()
    daemon = GatewayDaemon(config=config, state=state, telegram=telegram, codex=codex)

    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="I exported the updated diagram.",
        )
    )
    codex.append_event(
        CodexEvent(
            event_id="thread-1:turn-1:item-1:artifact:photo",
            thread_id="thread-1",
            kind="artifact_photo",
            text="Artifact: artifacts/diagram.png",
            file_path=str(artifact_path),
        )
    )

    daemon.sync_codex_once()

    assert non_bubble_sent_messages(telegram) == [
        (-100100, binding.message_thread_id, "I exported the updated diagram.", None)
    ]
    assert telegram.sent_photos == [
        (-100100, binding.message_thread_id, str(artifact_path), "Artifact: artifacts/diagram.png")
    ]


def test_gateway_flow_transcribes_voice_and_routes_confirmed_text_to_codex(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    voice_path = tmp_path / ".ccgram-uploads" / "voice.ogg"
    voice_path.parent.mkdir(parents=True)
    voice_path.write_bytes(b"ogg-bytes")
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Voice flow",
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
    service = GatewayService(config=config, state=state, telegram=telegram, codex=codex)
    binding = service.link_current_thread()
    daemon = GatewayDaemon(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
        transcriber=StaticTranscriptionProvider("Please continue with the deployment."),
    )

    telegram._updates.append(
        {
            "kind": "voice_message",
            "update_id": 1,
            "chat_id": -100100,
            "message_thread_id": binding.message_thread_id,
            "from_user_id": 111,
            "file_path": str(voice_path),
        }
    )
    daemon.poll_telegram_once()
    telegram.push_callback_query(
        update_id=2,
        callback_query_id="cb-voice-send",
        chat_id=-100100,
        message_thread_id=binding.message_thread_id,
        message_id=1,
        from_user_id=111,
        data="gw:voice:send",
    )

    daemon.poll_telegram_once()
    daemon.deliver_inbound_once()

    assert codex.started_turns == [
        StartedTurn(
            thread_id="thread-1",
            text="Please continue with the deployment.",
            local_image_paths=(),
        )
    ]


def test_gateway_flow_answers_inline_query_with_sendable_results(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Inline query topic",
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
    state.remember_passthrough_command("status")
    daemon = GatewayDaemon(
        config=config,
        state=state,
        telegram=telegram,
        codex=codex,
    )

    telegram.push_inline_query(
        update_id=1,
        inline_query_id="inline-1",
        from_user_id=111,
        query="sta",
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


def test_gateway_recall_command_renders_recent_topic_history(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    telegram = FakeTelegramClient()
    codex = FakeCodexBridge(
        CodexThread(
            thread_id="thread-1",
            title="Recall flow",
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
    service = GatewayService(config=config, state=state, telegram=telegram, codex=codex)
    binding = service.link_current_thread()
    state.record_topic_history(-100100, binding.message_thread_id, text="Please continue with the refactor.")
    state.record_topic_history(
        -100100,
        binding.message_thread_id,
        text="Please inspect the screenshots.",
        local_image_paths=("/tmp/one.png", "/tmp/two.png"),
    )
    daemon = GatewayDaemon(config=config, state=state, telegram=telegram, codex=codex)

    telegram.push_update(
        update_id=1,
        chat_id=-100100,
        message_thread_id=binding.message_thread_id,
        from_user_id=111,
        text="/gateway recall",
    )
    daemon.poll_telegram_once()

    assert telegram.sent_messages[-1] == (
        -100100,
        binding.message_thread_id,
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
