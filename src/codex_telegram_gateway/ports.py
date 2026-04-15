from collections.abc import Callable
from typing import Protocol

from codex_telegram_gateway.models import (
    Binding,
    CodexEvent,
    CodexHistoryEntry,
    CodexProject,
    CodexThread,
    HistoryViewState,
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


class TelegramClient(Protocol):
    """Telegram transport required by the gateway."""

    def create_forum_topic(self, chat_id: int, name: str) -> int:
        ...

    def get_chat(self, chat_id: int) -> dict[str, object]:
        ...

    def get_updates(self, offset: int | None = None) -> list[dict[str, object]]:
        ...

    def send_message(
        self,
        chat_id: int,
        message_thread_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> int:
        ...

    def send_chat_action(self, chat_id: int, message_thread_id: int, action: str) -> None:
        ...

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        ...

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict[str, object] | None,
    ) -> None:
        ...

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> None:
        ...

    def edit_forum_topic(self, chat_id: int, message_thread_id: int, name: str) -> None:
        ...

    def close_forum_topic(self, chat_id: int, message_thread_id: int) -> None:
        ...

    def probe_topic(self, chat_id: int, message_thread_id: int) -> bool:
        ...


class CodexBridge(Protocol):
    """Codex thread operations required by the gateway."""

    def get_current_thread_id(self) -> str:
        ...

    def list_loaded_threads(self) -> list[CodexThread]:
        ...

    def list_loaded_projects(self) -> list[CodexProject]:
        ...

    def list_all_threads(self) -> list[CodexThread]:
        ...

    def list_workspace_threads(self, cwd: str) -> list[CodexThread]:
        ...

    def read_thread(self, thread_id: str) -> CodexThread:
        ...

    def list_events(self, thread_id: str) -> list[CodexEvent]:
        ...

    def list_history_entries(self, thread_id: str) -> list[CodexHistoryEntry]:
        ...

    def create_thread(self, project_id: str, thread_name: str | None = None) -> CodexThread:
        ...

    def rename_thread(self, thread_id: str, thread_name: str) -> CodexThread:
        ...

    def ensure_project_visible(self, project_id: str) -> None:
        ...

    def start_turn(
        self,
        started_turn: StartedTurn,
        on_progress: Callable[[], None] | None = None,
    ) -> TurnResult:
        ...

    def steer_turn(
        self,
        started_turn: StartedTurn,
        expected_turn_id: str,
        on_progress: Callable[[], None] | None = None,
    ) -> TurnResult:
        ...

    def inspect_turn(self, thread_id: str, turn_id: str) -> TurnResult:
        ...


class GatewayState(Protocol):
    """Persistence operations for stable thread-id to topic-id routing."""

    def create_binding(self, binding: Binding) -> Binding:
        ...

    def list_bindings(self) -> list[Binding]:
        ...

    def get_binding_by_thread(self, codex_thread_id: str) -> Binding:
        ...

    def get_binding_by_topic(self, chat_id: int, message_thread_id: int) -> Binding | None:
        ...

    def upsert_mirror_binding(self, binding: Binding) -> Binding:
        ...

    def list_mirror_bindings(self) -> list[Binding]:
        ...

    def list_mirror_bindings_for_thread(self, codex_thread_id: str) -> list[Binding]:
        ...

    def get_mirror_binding_by_topic(self, chat_id: int, message_thread_id: int) -> Binding | None:
        ...

    def upsert_project(self, project: CodexProject) -> CodexProject:
        ...

    def list_projects(self) -> list[CodexProject]:
        ...

    def get_project(self, project_id: str) -> CodexProject:
        ...

    def upsert_topic_project(self, topic_project: TopicProject) -> TopicProject:
        ...

    def get_topic_project(self, chat_id: int, message_thread_id: int) -> TopicProject | None:
        ...

    def delete_topic_project(self, chat_id: int, message_thread_id: int) -> None:
        ...

    def mark_event_seen(self, codex_thread_id: str, event_id: str) -> None:
        ...

    def has_seen_event(self, codex_thread_id: str, event_id: str) -> bool:
        ...

    def delete_seen_event(self, codex_thread_id: str, event_id: str) -> None:
        ...

    def enqueue_inbound(self, inbound_message: InboundMessage) -> None:
        ...

    def list_pending_inbound(self) -> list[InboundMessage]:
        ...

    def mark_inbound_delivered(self, telegram_update_id: int) -> None:
        ...

    def set_telegram_cursor(self, update_id: int) -> None:
        ...

    def get_telegram_cursor(self) -> int:
        ...

    def pending_inbound_count(self) -> int:
        ...

    def upsert_outbound_message(self, outbound_message: OutboundMessage) -> OutboundMessage:
        ...

    def get_outbound_message(self, codex_thread_id: str, event_id: str) -> OutboundMessage | None:
        ...

    def delete_outbound_messages(self, codex_thread_id: str) -> None:
        ...

    def upsert_mirror_outbound_message(self, outbound_message: OutboundMessage, *, chat_id: int, message_thread_id: int) -> OutboundMessage:
        ...

    def get_mirror_outbound_message(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> OutboundMessage | None:
        ...

    def delete_mirror_outbound_messages(self, codex_thread_id: str, *, chat_id: int) -> None:
        ...

    def record_topic_history(
        self,
        chat_id: int,
        message_thread_id: int,
        *,
        text: str = "",
        local_image_paths: tuple[str, ...] = (),
    ) -> None:
        ...

    def list_topic_history(
        self,
        chat_id: int,
        message_thread_id: int,
        *,
        limit: int = 20,
    ) -> list[TopicHistoryEntry]:
        ...

    def upsert_history_view(self, history_view: HistoryViewState) -> HistoryViewState:
        ...

    def get_history_view(self, chat_id: int, message_thread_id: int) -> HistoryViewState | None:
        ...

    def delete_history_view(self, chat_id: int, message_thread_id: int) -> None:
        ...

    def upsert_pending_turn(self, pending_turn: PendingTurn) -> PendingTurn:
        ...

    def get_pending_turn(self, codex_thread_id: str) -> PendingTurn | None:
        ...

    def list_pending_turns(self) -> list[PendingTurn]:
        ...

    def delete_pending_turn(self, codex_thread_id: str) -> None:
        ...

    def mark_mirror_event_seen(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> None:
        ...

    def has_mirror_seen_event(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> bool:
        ...

    def delete_mirror_seen_event(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> None:
        ...

    def upsert_topic_lifecycle(self, topic_lifecycle: TopicLifecycle) -> TopicLifecycle:
        ...

    def get_topic_lifecycle(self, codex_thread_id: str) -> TopicLifecycle | None:
        ...

    def list_topic_lifecycles(self) -> list[TopicLifecycle]:
        ...

    def delete_topic_lifecycle(self, codex_thread_id: str) -> None:
        ...

    def set_topic_project_last_seen(self, chat_id: int, message_thread_id: int, seen_at: float) -> None:
        ...

    def get_topic_project_last_seen(self, chat_id: int, message_thread_id: int) -> float | None:
        ...

    def list_topic_project_last_seen(self) -> list[tuple[int, int, float]]:
        ...

    def delete_topic_project_last_seen(self, chat_id: int, message_thread_id: int) -> None:
        ...

    def prune_orphan_topic_history(self, live_topics: set[tuple[int, int]]) -> None:
        ...

    def upsert_topic_creation_job(self, topic_creation_job: TopicCreationJob) -> TopicCreationJob:
        ...

    def get_topic_creation_job(self, codex_thread_id: str, chat_id: int) -> TopicCreationJob | None:
        ...

    def list_topic_creation_jobs(self) -> list[TopicCreationJob]:
        ...

    def delete_topic_creation_job(self, codex_thread_id: str, chat_id: int) -> None:
        ...
