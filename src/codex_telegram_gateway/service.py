import time
from pathlib import Path

from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.models import (
    ACTIVE_BINDING_STATUS,
    Binding,
    TopicCreationJob,
    TopicLifecycle,
)
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
        thread = self._codex.read_thread(thread_id)
        try:
            # Existing thread-id mapping wins even if titles drift later.
            existing_binding = self._state.get_binding_by_thread(thread_id)
            self._queue_mirror_creation_jobs(existing_binding, thread_title=thread.title, project_id=thread.cwd or None)
            return existing_binding
        except KeyError:
            pass

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
        self._queue_mirror_creation_jobs(
            created_binding,
            thread_title=thread.title,
            project_id=thread.cwd or None,
        )
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
        self._queue_mirror_creation_jobs(
            created_binding,
            thread_title=created_thread.title,
            project_id=project_id,
        )
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
        latest_event_id = _latest_visible_event_id(self._codex.list_events(codex_thread_id))
        if latest_event_id is not None:
            self._state.delete_seen_event(codex_thread_id, latest_event_id)
        self._queue_mirror_creation_jobs(
            recreated_binding,
            thread_title=thread.title,
            project_id=recreated_binding.project_id,
        )
        return recreated_binding

    def rebind_topic_to_thread(
        self,
        *,
        chat_id: int,
        message_thread_id: int,
        codex_thread_id: str,
    ) -> Binding:
        thread = self._codex.read_thread(codex_thread_id)
        if thread.status == "notLoaded":
            thread = self._codex.resume_thread(codex_thread_id)
        topic_name = format_topic_name(thread.cwd, thread.title)
        self._telegram.edit_forum_topic(chat_id, message_thread_id, topic_name)
        rebound_binding = self._state.create_binding(
            Binding(
                codex_thread_id=codex_thread_id,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                topic_name=topic_name,
                sync_mode=self._config.sync_mode,
                project_id=thread.cwd or None,
                binding_status=ACTIVE_BINDING_STATUS,
            )
        )
        self._state.upsert_topic_lifecycle(
            TopicLifecycle(
                codex_thread_id=rebound_binding.codex_thread_id,
                chat_id=rebound_binding.chat_id,
                message_thread_id=rebound_binding.message_thread_id,
                bound_at=time.time(),
            )
        )
        for event in self._codex.list_events(codex_thread_id):
            self._state.mark_event_seen(codex_thread_id, event.event_id)
        self._queue_mirror_creation_jobs(
            rebound_binding,
            thread_title=thread.title,
            project_id=thread.cwd or None,
        )
        return rebound_binding

    def _queue_mirror_creation_jobs(
        self,
        binding: Binding,
        *,
        thread_title: str,
        project_id: str | None,
    ) -> None:
        mirror_chat_ids = [
            chat_id
            for chat_id in self._config.telegram_target_chat_ids
            if chat_id != binding.chat_id
        ]
        if not mirror_chat_ids:
            return
        topic_name = format_topic_name(project_id or "", thread_title)
        existing_mirror_chat_ids = {
            mirror_binding.chat_id
            for mirror_binding in self._state.list_mirror_bindings_for_thread(binding.codex_thread_id)
        }
        for chat_id in mirror_chat_ids:
            if chat_id in existing_mirror_chat_ids:
                continue
            self._state.upsert_topic_creation_job(
                TopicCreationJob(
                    codex_thread_id=binding.codex_thread_id,
                    chat_id=chat_id,
                    topic_name=topic_name,
                    project_id=project_id,
                )
            )

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


def _latest_visible_event_id(events) -> str | None:
    for event in reversed(list(events)):
        if event.kind in {"assistant_message", "tool_batch", "completion_summary"}:
            return event.event_id
    return None
