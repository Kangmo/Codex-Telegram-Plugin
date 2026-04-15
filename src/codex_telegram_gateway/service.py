import time
from pathlib import Path

from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.models import ACTIVE_BINDING_STATUS, Binding, TopicLifecycle
from codex_telegram_gateway.ports import CodexBridge, GatewayState, TelegramClient


DEFAULT_NEW_THREAD_TITLE = "untitled"


class GatewayService:
    """Application service for persisted thread-id to topic-id bindings."""

    def __init__(
        self,
        *,
        config: GatewayConfig,
        state: GatewayState,
        telegram: TelegramClient,
        codex: CodexBridge,
    ) -> None:
        self._config = config
        self._state = state
        self._telegram = telegram
        self._codex = codex

    def link_current_thread(self) -> Binding:
        return self.link_thread(self._codex.get_current_thread_id())

    def link_loaded_threads(self) -> list[Binding]:
        return [self.link_thread(thread.thread_id) for thread in self._codex.list_loaded_threads()]

    def link_thread(self, thread_id: str) -> Binding:
        try:
            # Existing thread-id mapping wins even if titles drift later.
            return self._state.get_binding_by_thread(thread_id)
        except KeyError:
            pass

        thread = self._codex.read_thread(thread_id)
        topic_name = format_topic_name(thread.cwd, thread.title)
        message_thread_id = self._telegram.create_forum_topic(
            self._config.telegram_default_chat_id,
            topic_name,
        )
        binding = Binding(
            codex_thread_id=thread_id,
            chat_id=self._config.telegram_default_chat_id,
            message_thread_id=message_thread_id,
            topic_name=topic_name,
            sync_mode=self._config.sync_mode,
            project_id=thread.cwd or None,
            binding_status=ACTIVE_BINDING_STATUS,
        )
        created_binding = self._state.create_binding(binding)
        self._state.upsert_topic_lifecycle(
            TopicLifecycle(
                codex_thread_id=created_binding.codex_thread_id,
                chat_id=created_binding.chat_id,
                message_thread_id=created_binding.message_thread_id,
                bound_at=time.time(),
            )
        )
        for event in self._codex.list_events(thread_id):
            self._state.mark_event_seen(thread_id, event.event_id)
        return created_binding

    def bind_topic_to_project(
        self,
        *,
        chat_id: int,
        message_thread_id: int,
        project_id: str,
        thread_title: str = DEFAULT_NEW_THREAD_TITLE,
    ) -> Binding:
        created_thread = self._codex.create_thread(
            project_id=project_id,
            thread_name=_normalize_thread_title(thread_title),
        )
        topic_name = format_topic_name(project_id, created_thread.title)
        self._telegram.edit_forum_topic(chat_id, message_thread_id, topic_name)
        binding = Binding(
            codex_thread_id=created_thread.thread_id,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            topic_name=topic_name,
            sync_mode=self._config.sync_mode,
            project_id=project_id,
            binding_status=ACTIVE_BINDING_STATUS,
        )
        created_binding = self._state.create_binding(binding)
        self._state.upsert_topic_lifecycle(
            TopicLifecycle(
                codex_thread_id=created_binding.codex_thread_id,
                chat_id=created_binding.chat_id,
                message_thread_id=created_binding.message_thread_id,
                bound_at=time.time(),
            )
        )
        for event in self._codex.list_events(created_thread.thread_id):
            self._state.mark_event_seen(created_thread.thread_id, event.event_id)
        return created_binding

    def recreate_topic(self, codex_thread_id: str) -> Binding:
        existing_binding = self._state.get_binding_by_thread(codex_thread_id)
        thread = self._codex.read_thread(codex_thread_id)
        topic_name = format_topic_name(existing_binding.project_id or thread.cwd, thread.title)
        message_thread_id = self._telegram.create_forum_topic(existing_binding.chat_id, topic_name)
        recreated_binding = Binding(
            codex_thread_id=codex_thread_id,
            chat_id=existing_binding.chat_id,
            message_thread_id=message_thread_id,
            topic_name=topic_name,
            sync_mode=existing_binding.sync_mode,
            project_id=existing_binding.project_id or thread.cwd or None,
            binding_status=ACTIVE_BINDING_STATUS,
        )
        self._state.create_binding(recreated_binding)
        self._state.upsert_topic_lifecycle(
            TopicLifecycle(
                codex_thread_id=recreated_binding.codex_thread_id,
                chat_id=recreated_binding.chat_id,
                message_thread_id=recreated_binding.message_thread_id,
                bound_at=time.time(),
            )
        )
        self._state.delete_outbound_messages(codex_thread_id)
        latest_assistant_event_id = _latest_assistant_event_id(self._codex.list_events(codex_thread_id))
        if latest_assistant_event_id is not None:
            self._state.delete_seen_event(codex_thread_id, latest_assistant_event_id)
        return recreated_binding

def format_topic_name(project_id: str, thread_title: str) -> str:
    project_name = Path(project_id).name.strip()
    if not project_name:
        return thread_title
    return f"({project_name}) {thread_title}"


def _normalize_thread_title(thread_title: str, limit: int = 96) -> str:
    collapsed = " ".join(part for part in thread_title.split())
    if not collapsed:
        return "Telegram topic"
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _latest_assistant_event_id(events) -> str | None:
    for event in reversed(list(events)):
        if event.kind == "assistant_message":
            return event.event_id
    return None
