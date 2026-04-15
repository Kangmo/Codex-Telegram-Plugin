from codex_telegram_gateway.models import (
    Binding,
    CodexEvent,
    CodexProject,
    CodexThread,
    InboundMessage,
    OutboundMessage,
    PendingTurn,
    TopicCreationJob,
    StartedTurn,
    TopicLifecycle,
    TopicHistoryEntry,
    TopicProject,
    TurnResult,
)


class DummyState:
    """In-memory state double used by unit tests."""

    def __init__(self) -> None:
        self.bindings_by_thread: dict[str, Binding] = {}
        self.bindings_by_topic: dict[tuple[int, int], Binding] = {}
        self.mirror_bindings_by_thread_chat: dict[tuple[str, int], Binding] = {}
        self.mirror_bindings_by_topic: dict[tuple[int, int], Binding] = {}
        self.projects: dict[str, CodexProject] = {}
        self.topic_projects: dict[tuple[int, int], TopicProject] = {}
        self.seen_events: set[tuple[str, str]] = set()
        self.mirror_seen_events: set[tuple[str, int, int, str]] = set()
        self.outbound_messages: dict[tuple[str, str], OutboundMessage] = {}
        self.mirror_outbound_messages: dict[tuple[str, int, int, str], OutboundMessage] = {}
        self.inbound_messages: list[InboundMessage] = []
        self.pending_turns: dict[str, PendingTurn] = {}
        self.topic_lifecycles: dict[str, TopicLifecycle] = {}
        self.topic_history: dict[tuple[int, int], list[TopicHistoryEntry]] = {}
        self.topic_project_last_seen: dict[tuple[int, int], float] = {}
        self.topic_creation_jobs: dict[tuple[str, int], TopicCreationJob] = {}
        self.telegram_cursor = 0

    def create_binding(self, binding: Binding) -> Binding:
        existing_by_thread = self.bindings_by_thread.get(binding.codex_thread_id)
        if existing_by_thread is not None:
            self.bindings_by_topic.pop(
                (existing_by_thread.chat_id, existing_by_thread.message_thread_id),
                None,
            )
        existing_by_topic = self.bindings_by_topic.get((binding.chat_id, binding.message_thread_id))
        if existing_by_topic is not None:
            self.bindings_by_thread.pop(existing_by_topic.codex_thread_id, None)
        self.bindings_by_thread[binding.codex_thread_id] = binding
        self.bindings_by_topic[(binding.chat_id, binding.message_thread_id)] = binding
        return binding

    def get_binding_by_thread(self, codex_thread_id: str) -> Binding:
        return self.bindings_by_thread[codex_thread_id]

    def get_binding_by_topic(self, chat_id: int, message_thread_id: int) -> Binding | None:
        return self.bindings_by_topic.get((chat_id, message_thread_id))

    def list_bindings(self) -> list[Binding]:
        return list(self.bindings_by_thread.values())

    def upsert_mirror_binding(self, binding: Binding) -> Binding:
        existing = self.mirror_bindings_by_thread_chat.get((binding.codex_thread_id, binding.chat_id))
        if existing is not None:
            self.mirror_bindings_by_topic.pop((existing.chat_id, existing.message_thread_id), None)
        existing_by_topic = self.mirror_bindings_by_topic.get((binding.chat_id, binding.message_thread_id))
        if existing_by_topic is not None:
            self.mirror_bindings_by_thread_chat.pop((existing_by_topic.codex_thread_id, existing_by_topic.chat_id), None)
        self.mirror_bindings_by_thread_chat[(binding.codex_thread_id, binding.chat_id)] = binding
        self.mirror_bindings_by_topic[(binding.chat_id, binding.message_thread_id)] = binding
        return binding

    def list_mirror_bindings(self) -> list[Binding]:
        return list(self.mirror_bindings_by_thread_chat.values())

    def list_mirror_bindings_for_thread(self, codex_thread_id: str) -> list[Binding]:
        return [
            binding
            for (thread_id, _chat_id), binding in self.mirror_bindings_by_thread_chat.items()
            if thread_id == codex_thread_id
        ]

    def get_mirror_binding_by_topic(self, chat_id: int, message_thread_id: int) -> Binding | None:
        return self.mirror_bindings_by_topic.get((chat_id, message_thread_id))

    def upsert_project(self, project: CodexProject) -> CodexProject:
        self.projects[project.project_id] = project
        return project

    def list_projects(self) -> list[CodexProject]:
        return sorted(self.projects.values(), key=lambda project: (project.project_name, project.project_id))

    def get_project(self, project_id: str) -> CodexProject:
        return self.projects[project_id]

    def upsert_topic_project(self, topic_project: TopicProject) -> TopicProject:
        self.topic_projects[(topic_project.chat_id, topic_project.message_thread_id)] = topic_project
        return topic_project

    def get_topic_project(self, chat_id: int, message_thread_id: int) -> TopicProject | None:
        return self.topic_projects.get((chat_id, message_thread_id))

    def delete_topic_project(self, chat_id: int, message_thread_id: int) -> None:
        self.topic_projects.pop((chat_id, message_thread_id), None)

    def mark_event_seen(self, codex_thread_id: str, event_id: str) -> None:
        self.seen_events.add((codex_thread_id, event_id))

    def has_seen_event(self, codex_thread_id: str, event_id: str) -> bool:
        return (codex_thread_id, event_id) in self.seen_events

    def delete_seen_event(self, codex_thread_id: str, event_id: str) -> None:
        self.seen_events.discard((codex_thread_id, event_id))

    def mark_mirror_event_seen(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> None:
        self.mirror_seen_events.add((codex_thread_id, chat_id, message_thread_id, event_id))

    def has_mirror_seen_event(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> bool:
        return (codex_thread_id, chat_id, message_thread_id, event_id) in self.mirror_seen_events

    def delete_mirror_seen_event(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> None:
        self.mirror_seen_events.discard((codex_thread_id, chat_id, message_thread_id, event_id))

    def enqueue_inbound(self, inbound_message: InboundMessage) -> None:
        self.inbound_messages.append(inbound_message)

    def list_pending_inbound(self) -> list[InboundMessage]:
        return list(self.inbound_messages)

    def mark_inbound_delivered(self, telegram_update_id: int) -> None:
        self.inbound_messages = [
            message
            for message in self.inbound_messages
            if message.telegram_update_id != telegram_update_id
        ]

    def set_telegram_cursor(self, update_id: int) -> None:
        self.telegram_cursor = update_id

    def get_telegram_cursor(self) -> int:
        return self.telegram_cursor

    def pending_inbound_count(self) -> int:
        return len(self.inbound_messages)

    def upsert_outbound_message(self, outbound_message: OutboundMessage) -> OutboundMessage:
        self.outbound_messages[(outbound_message.codex_thread_id, outbound_message.event_id)] = outbound_message
        return outbound_message

    def get_outbound_message(self, codex_thread_id: str, event_id: str) -> OutboundMessage | None:
        return self.outbound_messages.get((codex_thread_id, event_id))

    def delete_outbound_messages(self, codex_thread_id: str) -> None:
        self.outbound_messages = {
            key: value
            for key, value in self.outbound_messages.items()
            if key[0] != codex_thread_id
        }

    def upsert_mirror_outbound_message(
        self,
        outbound_message: OutboundMessage,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> OutboundMessage:
        self.mirror_outbound_messages[
            (outbound_message.codex_thread_id, chat_id, message_thread_id, outbound_message.event_id)
        ] = outbound_message
        return outbound_message

    def get_mirror_outbound_message(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> OutboundMessage | None:
        return self.mirror_outbound_messages.get((codex_thread_id, chat_id, message_thread_id, event_id))

    def delete_mirror_outbound_messages(self, codex_thread_id: str, *, chat_id: int) -> None:
        self.mirror_outbound_messages = {
            key: value
            for key, value in self.mirror_outbound_messages.items()
            if not (key[0] == codex_thread_id and key[1] == chat_id)
        }

    def record_topic_history(
        self,
        chat_id: int,
        message_thread_id: int,
        *,
        text: str = "",
        local_image_paths: tuple[str, ...] = (),
    ) -> None:
        normalized_text = text.strip()
        if not normalized_text and not local_image_paths:
            return
        key = (chat_id, message_thread_id)
        entry = TopicHistoryEntry(
            text=normalized_text,
            local_image_paths=local_image_paths,
        )
        history = self.topic_history.setdefault(key, [])
        if history and history[0] == entry:
            return
        history.insert(0, entry)
        del history[20:]

    def list_topic_history(
        self,
        chat_id: int,
        message_thread_id: int,
        *,
        limit: int = 20,
    ) -> list[TopicHistoryEntry]:
        return list(self.topic_history.get((chat_id, message_thread_id), [])[:limit])

    def upsert_pending_turn(self, pending_turn: PendingTurn) -> PendingTurn:
        self.pending_turns[pending_turn.codex_thread_id] = pending_turn
        return pending_turn

    def get_pending_turn(self, codex_thread_id: str) -> PendingTurn | None:
        return self.pending_turns.get(codex_thread_id)

    def list_pending_turns(self) -> list[PendingTurn]:
        return list(self.pending_turns.values())

    def delete_pending_turn(self, codex_thread_id: str) -> None:
        self.pending_turns.pop(codex_thread_id, None)

    def upsert_topic_lifecycle(self, topic_lifecycle: TopicLifecycle) -> TopicLifecycle:
        self.topic_lifecycles[topic_lifecycle.codex_thread_id] = topic_lifecycle
        return topic_lifecycle

    def get_topic_lifecycle(self, codex_thread_id: str) -> TopicLifecycle | None:
        return self.topic_lifecycles.get(codex_thread_id)

    def list_topic_lifecycles(self) -> list[TopicLifecycle]:
        return list(self.topic_lifecycles.values())

    def delete_topic_lifecycle(self, codex_thread_id: str) -> None:
        self.topic_lifecycles.pop(codex_thread_id, None)

    def set_topic_project_last_seen(self, chat_id: int, message_thread_id: int, seen_at: float) -> None:
        self.topic_project_last_seen[(chat_id, message_thread_id)] = seen_at

    def get_topic_project_last_seen(self, chat_id: int, message_thread_id: int) -> float | None:
        return self.topic_project_last_seen.get((chat_id, message_thread_id))

    def list_topic_project_last_seen(self) -> list[tuple[int, int, float]]:
        return [
            (chat_id, message_thread_id, seen_at)
            for (chat_id, message_thread_id), seen_at in self.topic_project_last_seen.items()
        ]

    def delete_topic_project_last_seen(self, chat_id: int, message_thread_id: int) -> None:
        self.topic_project_last_seen.pop((chat_id, message_thread_id), None)

    def prune_orphan_topic_history(self, live_topics: set[tuple[int, int]]) -> None:
        self.topic_history = {
            key: value
            for key, value in self.topic_history.items()
            if key in live_topics
        }

    def upsert_topic_creation_job(self, topic_creation_job: TopicCreationJob) -> TopicCreationJob:
        self.topic_creation_jobs[(topic_creation_job.codex_thread_id, topic_creation_job.chat_id)] = topic_creation_job
        return topic_creation_job

    def get_topic_creation_job(self, codex_thread_id: str, chat_id: int) -> TopicCreationJob | None:
        return self.topic_creation_jobs.get((codex_thread_id, chat_id))

    def list_topic_creation_jobs(self) -> list[TopicCreationJob]:
        return list(self.topic_creation_jobs.values())

    def delete_topic_creation_job(self, codex_thread_id: str, chat_id: int) -> None:
        self.topic_creation_jobs.pop((codex_thread_id, chat_id), None)


class DummyTelegramClient:
    """In-memory Telegram client double used by unit tests."""

    def __init__(self) -> None:
        self._next_topic_id = 1
        self._updates: list[dict[str, object]] = []
        self._next_message_id = 1
        self.dead_topics: set[tuple[int, int]] = set()
        self.created_topics: list[tuple[int, str]] = []
        self.sent_messages: list[tuple[int, int, str, dict[str, object] | None]] = []
        self.sent_chat_actions: list[tuple[int, int, str]] = []
        self.answered_callback_queries: list[tuple[str, str | None]] = []
        self.edited_reply_markups: list[tuple[int, int, dict[str, object] | None]] = []
        self.edited_messages: list[tuple[int, int, str, dict[str, object] | None]] = []
        self.edited_topics: list[tuple[int, int, str]] = []
        self.closed_topics: list[tuple[int, int]] = []

    def create_forum_topic(self, chat_id: int, name: str) -> int:
        topic_id = self._next_topic_id
        self._next_topic_id += 1
        self.created_topics.append((chat_id, name))
        return topic_id

    def get_chat(self, chat_id: int) -> dict[str, object]:
        return {"id": chat_id, "title": "dummy-chat", "type": "supergroup"}

    def get_updates(self, offset: int | None = None) -> list[dict[str, object]]:
        if offset is None:
            return list(self._updates)
        return [update for update in self._updates if int(update["update_id"]) >= offset]

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

    def push_topic_created_update(
        self,
        *,
        update_id: int,
        chat_id: int,
        message_thread_id: int,
        from_user_id: int,
        topic_name: str,
    ) -> None:
        self._updates.append(
            {
                "kind": "topic_created",
                "update_id": update_id,
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "from_user_id": from_user_id,
                "topic_name": topic_name,
            }
        )

    def push_topic_closed_update(
        self,
        *,
        update_id: int,
        chat_id: int,
        message_thread_id: int,
        from_user_id: int,
    ) -> None:
        self._updates.append(
            {
                "kind": "topic_closed",
                "update_id": update_id,
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "from_user_id": from_user_id,
            }
        )

    def push_topic_reopened_update(
        self,
        *,
        update_id: int,
        chat_id: int,
        message_thread_id: int,
        from_user_id: int,
    ) -> None:
        self._updates.append(
            {
                "kind": "topic_reopened",
                "update_id": update_id,
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "from_user_id": from_user_id,
            }
        )

    def push_topic_edited_update(
        self,
        *,
        update_id: int,
        chat_id: int,
        message_thread_id: int,
        from_user_id: int,
        topic_name: str,
    ) -> None:
        self._updates.append(
            {
                "kind": "topic_edited",
                "update_id": update_id,
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "from_user_id": from_user_id,
                "topic_name": topic_name,
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
        self.answered_callback_queries.append((callback_query_id, text))

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict[str, object] | None,
    ) -> None:
        self.edited_reply_markups.append((chat_id, message_id, reply_markup))

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
        self.closed_topics.append((chat_id, message_thread_id))

    def probe_topic(self, chat_id: int, message_thread_id: int) -> bool:
        return (chat_id, message_thread_id) not in self.dead_topics


class DummyCodexBridge:
    """In-memory Codex bridge double used by unit tests."""

    def __init__(self, thread: CodexThread) -> None:
        self.current_thread_id = thread.thread_id
        self._threads = {thread.thread_id: thread}
        self._events: dict[str, list[CodexEvent]] = {thread.thread_id: []}
        self.started_turns: list[StartedTurn] = []
        self.steered_turns: list[tuple[str, StartedTurn]] = []
        self.created_threads: list[CodexThread] = []
        self.ensured_projects: list[str] = []
        self.renamed_threads: list[tuple[str, str]] = []
        self.next_turn_result = TurnResult(turn_id="turn-1", status="in_progress")
        self.next_steer_result: TurnResult | None = None
        self.next_steer_error: RuntimeError | None = None
        self.inspect_results: dict[tuple[str, str], TurnResult] = {}

    def get_current_thread_id(self) -> str:
        return self.current_thread_id

    def list_loaded_threads(self) -> list[CodexThread]:
        return list(self._threads.values())

    def list_loaded_projects(self) -> list[CodexProject]:
        projects: dict[str, CodexProject] = {}
        for thread in self._threads.values():
            if not thread.cwd:
                continue
            projects.setdefault(
                thread.cwd,
                CodexProject(project_id=thread.cwd, project_name=thread.cwd.rstrip("/").split("/")[-1]),
            )
        return sorted(projects.values(), key=lambda project: (project.project_name, project.project_id))

    def list_all_threads(self) -> list[CodexThread]:
        return list(self._threads.values())

    def list_workspace_threads(self, cwd: str) -> list[CodexThread]:
        return list(self._threads.values())

    def read_thread(self, thread_id: str) -> CodexThread:
        return self._threads[thread_id]

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
        self.ensure_project_visible(project_id)
        thread_id = f"thread-{len(self._threads) + 1}"
        created_thread = CodexThread(
            thread_id=thread_id,
            title=thread_name or project_id.rstrip("/").split("/")[-1],
            status="idle",
            cwd=project_id,
        )
        self._threads[thread_id] = created_thread
        self._events[thread_id] = []
        self.created_threads.append(created_thread)
        return created_thread

    def ensure_project_visible(self, project_id: str) -> None:
        if project_id not in self.ensured_projects:
            self.ensured_projects.append(project_id)

    def rename_thread(self, thread_id: str, thread_name: str) -> CodexThread:
        self.renamed_threads.append((thread_id, thread_name))
        self.set_thread_title(thread_id, thread_name)
        return self.read_thread(thread_id)

    def start_turn(self, started_turn: StartedTurn, on_progress=None) -> TurnResult:
        self.started_turns.append(started_turn)
        if on_progress is not None:
            on_progress()
        result = self.next_turn_result
        self.inspect_results[(started_turn.thread_id, result.turn_id)] = result
        return result

    def steer_turn(self, started_turn: StartedTurn, expected_turn_id: str, on_progress=None) -> TurnResult:
        self.steered_turns.append((expected_turn_id, started_turn))
        if on_progress is not None:
            on_progress()
        if self.next_steer_error is not None:
            raise self.next_steer_error
        result = self.next_steer_result or TurnResult(turn_id=expected_turn_id, status="in_progress")
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

    def set_thread_title(self, thread_id: str, title: str) -> None:
        self._threads[thread_id] = CodexThread(
            thread_id=thread_id,
            title=title,
            status=self._threads[thread_id].status,
            cwd=self._threads[thread_id].cwd,
        )
