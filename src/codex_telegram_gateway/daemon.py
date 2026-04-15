import time
from dataclasses import dataclass, replace
from pathlib import Path
import re

from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.history_command import (
    CALLBACK_HISTORY_PREFIX,
    parse_history_callback,
    render_history_page,
)
from codex_telegram_gateway.models import (
    ACTIVE_BINDING_STATUS,
    Binding,
    CLOSED_BINDING_STATUS,
    CodexProject,
    CodexThread,
    DELETED_BINDING_STATUS,
    HistoryViewState,
    InboundMessage,
    OutboundMessage,
    PendingTurn,
    RestoreViewState,
    ResumeViewState,
    StartedTurn,
    TopicCreationJob,
    TopicLifecycle,
    TopicHistoryEntry,
    TopicProject,
    TurnResult,
)
from codex_telegram_gateway.ports import CodexBridge, GatewayState, TelegramClient
from codex_telegram_gateway.service import (
    DEFAULT_NEW_THREAD_TITLE,
    GatewayService,
    format_topic_name,
)
from codex_telegram_gateway.resume_command import (
    CALLBACK_RESUME_CANCEL,
    CALLBACK_RESUME_PAGE_PREFIX,
    CALLBACK_RESUME_PICK_PREFIX,
    parse_resume_page_callback,
    parse_resume_pick_callback,
    render_resume_picker,
)
from codex_telegram_gateway.recovery import (
    CALLBACK_RESTORE_CANCEL,
    CALLBACK_RESTORE_CONTINUE,
    CALLBACK_RESTORE_RECREATE,
    CALLBACK_RESTORE_RESUME,
    RESTORE_ISSUE_CLOSED,
    RESTORE_ISSUE_DELETED,
    render_restore_prompt,
)
from codex_telegram_gateway.telegram_api import (
    is_missing_topic_error,
    is_topic_edit_permission_error,
    TelegramRetryAfterError,
)
from codex_telegram_gateway.topic_status import (
    TOPIC_STATUS_APPROVAL,
    TOPIC_STATUS_CLOSED,
    TOPIC_STATUS_FAILED,
    TOPIC_STATUS_IDLE,
    TOPIC_STATUS_RUNNING,
    format_topic_title_for_status,
    strip_topic_status_prefix,
)
from codex_telegram_gateway.topic_lifecycle import (
    is_unbound_topic_expired,
    should_autoclose_topic,
    should_probe_topics,
    should_prune_state,
)

_UNSET = object()


class GatewayDaemon:
    """Sync loop entry points used by tests and the future daemon runner."""

    _TYPING_ACTION = "typing"
    _TYPING_INTERVAL_SECONDS = 4.0
    _TELEGRAM_MESSAGE_LIMIT = 4000

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
        self._last_typing_sent_at: dict[tuple[int, int], float] = {}
        self._topic_status_overrides: dict[tuple[int, int], str] = {}
        self._topic_status_disabled_chats: set[int] = set()
        self._lifecycle_timers = {
            "probe": 0.0,
            "autoclose": 0.0,
            "prune": 0.0,
            "unbound": 0.0,
        }
        self._service = GatewayService(
            config=config,
            state=state,
            telegram=telegram,
            codex=codex,
        )

    def sync_codex_once(self) -> None:
        self._sync_projects_once()
        self._sync_loaded_threads_once()
        self._process_topic_creation_jobs()
        pending_turns_by_thread = {
            pending_turn.codex_thread_id: pending_turn
            for pending_turn in self._state.list_pending_turns()
        }
        for binding in self._state.list_bindings():
            targets = self._targets_for_thread(binding.codex_thread_id)
            pending_turn = pending_turns_by_thread.get(binding.codex_thread_id)
            turn_result = None
            if pending_turn is not None:
                turn_result = self._codex.inspect_turn(binding.codex_thread_id, pending_turn.turn_id)
            thread = self._codex.read_thread(binding.codex_thread_id)
            active_targets: list[Binding] = []
            for target in targets:
                if target.binding_status == DELETED_BINDING_STATUS:
                    continue
                active_targets.append(target)
                topic_status = self._topic_status_for_binding(target, pending_turn, turn_result)
                base_topic_name = format_topic_name(binding.project_id or thread.cwd, thread.title)
                desired_topic_name = self._desired_topic_name(
                    target,
                    base_topic_name=base_topic_name,
                    topic_status=topic_status,
                )
                if not self._topic_name_matches_desired(
                    target,
                    desired_topic_name=desired_topic_name,
                    base_topic_name=base_topic_name,
                ):
                    target = self._sync_topic_name(
                        target,
                        desired_topic_name=desired_topic_name,
                        base_topic_name=base_topic_name,
                    )
                if target.binding_status == ACTIVE_BINDING_STATUS:
                    for event in self._codex.list_events(binding.codex_thread_id):
                        active_turn_id = pending_turn.turn_id if pending_turn is not None else None
                        active_turn_result = turn_result if active_turn_id == _event_turn_id(event.event_id) else None
                        self._sync_outbound_event(target, event, active_turn_result=active_turn_result)

            if pending_turn is None:
                continue
            if turn_result is None:
                turn_result = self._codex.inspect_turn(binding.codex_thread_id, pending_turn.turn_id)

            if turn_result.waiting_for_approval or not _is_terminal_turn_status(turn_result.status):
                for target in active_targets:
                    if target.binding_status == ACTIVE_BINDING_STATUS:
                        self._send_typing_if_due(target.chat_id, target.message_thread_id)
                    else:
                        self._clear_typing_state(target.chat_id, target.message_thread_id)
                continue

            self._state.delete_pending_turn(binding.codex_thread_id)
            for target in active_targets:
                if turn_result.status == "completed":
                    self._clear_topic_status_override(target.chat_id, target.message_thread_id)
                else:
                    self._set_topic_status_override(
                        target.chat_id,
                        target.message_thread_id,
                        TOPIC_STATUS_FAILED,
                    )
                self._clear_typing_state(target.chat_id, target.message_thread_id)
                if target.binding_status == ACTIVE_BINDING_STATUS and turn_result.status != "completed":
                    try:
                        self._telegram.send_message(
                            target.chat_id,
                            target.message_thread_id,
                            _turn_status_text(turn_result.status),
                        )
                    except Exception as exc:
                        if not self._mark_binding_deleted_if_missing_topic(target, exc):
                            raise
            if turn_result.status == "completed":
                self._mark_topic_completed(binding.codex_thread_id)

    def poll_telegram_once(self) -> None:
        self._sync_projects_once()
        offset = self._state.get_telegram_cursor()
        updates = self._telegram.get_updates(offset=offset)
        highest_seen = offset

        for update in updates:
            update_id = int(update["update_id"])
            highest_seen = max(highest_seen, update_id + 1)

            try:
                kind = str(update.get("kind") or "message")
                chat_id = int(update["chat_id"])
                message_thread_id = int(update["message_thread_id"])
                from_user_id = int(update["from_user_id"])

                if kind == "topic_created":
                    self._record_topic_created(update)
                    continue
                if kind == "topic_closed":
                    self._handle_topic_closed(update)
                    continue
                if kind == "topic_reopened":
                    self._handle_topic_reopened(update)
                    continue
                if kind == "topic_edited":
                    self._handle_topic_edited(update)
                    continue
                if kind == "callback_query":
                    if from_user_id not in self._config.telegram_allowed_user_ids:
                        continue
                    if self._binding_by_topic(chat_id, message_thread_id) is None:
                        self._state.set_topic_project_last_seen(chat_id, message_thread_id, time.time())
                    self._handle_callback_query(update)
                    continue
                if kind != "message":
                    continue

                if from_user_id not in self._config.telegram_allowed_user_ids:
                    continue

                text = str(update.get("text") or "")
                local_image_paths = _normalized_local_image_paths(update)
                if not text and not local_image_paths:
                    continue
                binding = self._binding_by_topic(chat_id, message_thread_id)
                if binding is not None and binding.binding_status != ACTIVE_BINDING_STATUS:
                    if self._is_primary_binding(binding):
                        self._offer_restore_prompt(binding)
                    continue
                command = _parse_command(text)
                if command is not None:
                    self._handle_command(update, command_name=command[0], command_args=command[1])
                    continue
                if binding is None:
                    self._handle_unbound_topic_message(update)
                    continue

                self._enqueue_bound_inbound(
                    binding,
                    telegram_update_id=update_id,
                    from_user_id=from_user_id,
                    text=text,
                    local_image_paths=local_image_paths,
                )
            except Exception:
                continue

        self._state.set_telegram_cursor(highest_seen)

    def deliver_inbound_once(self) -> None:
        self._sync_projects_once()
        for inbound_message in self._state.list_pending_inbound():
            pending_turn = self._state.get_pending_turn(inbound_message.codex_thread_id)
            if pending_turn is not None:
                self._send_typing_if_due(
                    pending_turn.chat_id,
                    pending_turn.message_thread_id,
                )
                continue

            binding = self._state.get_binding_by_thread(inbound_message.codex_thread_id)
            if binding.binding_status != ACTIVE_BINDING_STATUS:
                continue

            thread = self._codex.read_thread(inbound_message.codex_thread_id)
            if thread.status not in {"idle", "notLoaded"}:
                continue

            self._send_typing_if_due(
                inbound_message.chat_id,
                inbound_message.message_thread_id,
                force=True,
            )
            self._clear_topic_status_override(
                inbound_message.chat_id,
                inbound_message.message_thread_id,
            )
            turn_result = self._codex.start_turn(
                StartedTurn(
                    thread_id=inbound_message.codex_thread_id,
                    text=inbound_message.text,
                    local_image_paths=inbound_message.local_image_paths,
                ),
            )
            self._state.upsert_pending_turn(
                PendingTurn(
                    codex_thread_id=inbound_message.codex_thread_id,
                    chat_id=inbound_message.chat_id,
                    message_thread_id=inbound_message.message_thread_id,
                    turn_id=turn_result.turn_id,
                    waiting_for_approval=turn_result.waiting_for_approval,
                )
            )
            self._state.mark_inbound_delivered(inbound_message.telegram_update_id)
            return

    def _sync_outbound_event(self, binding, event, *, active_turn_result: TurnResult | None = None) -> None:
        if event.kind != "assistant_message":
            return
        reply_markup = self._assistant_reply_markup(binding, active_turn_result)

        outbound_message = self._get_outbound_message_for_target(binding, event.event_id)
        if outbound_message is None:
            if self._has_seen_event_for_target(binding, event.event_id):
                return
            try:
                outbound_message = OutboundMessage(
                    codex_thread_id=binding.codex_thread_id,
                    event_id=event.event_id,
                    telegram_message_ids=self._send_message_parts(
                        binding.chat_id,
                        binding.message_thread_id,
                        event.text,
                        reply_markup=reply_markup,
                    ),
                    text=event.text,
                    reply_markup=reply_markup,
                )
            except Exception as exc:
                if self._mark_binding_deleted_if_missing_topic(binding, exc):
                    return
                raise
            self._upsert_outbound_message_for_target(binding, outbound_message)
            self._mark_event_seen_for_target(binding, event.event_id)
            if self._is_primary_binding(binding):
                self._touch_topic_lifecycle(binding.codex_thread_id, last_outbound_at=time.time())
            return

        if outbound_message.text == event.text and outbound_message.reply_markup == reply_markup:
            return

        try:
            updated_message_ids = self._sync_message_parts(
                binding.chat_id,
                binding.message_thread_id,
                outbound_message.telegram_message_ids,
                outbound_message.text,
                event.text,
                previous_reply_markup=outbound_message.reply_markup,
                next_reply_markup=reply_markup,
            )
        except Exception as exc:
            if self._mark_binding_deleted_if_missing_topic(binding, exc):
                return
            raise
        self._upsert_outbound_message_for_target(
            binding,
            OutboundMessage(
                codex_thread_id=outbound_message.codex_thread_id,
                event_id=outbound_message.event_id,
                telegram_message_ids=updated_message_ids,
                text=event.text,
                reply_markup=reply_markup,
            )
        )
        if self._is_primary_binding(binding):
            self._touch_topic_lifecycle(binding.codex_thread_id, last_outbound_at=time.time())

    def _sync_projects_once(self) -> None:
        for project in self._codex.list_loaded_projects():
            self._state.upsert_project(project)
        for project in self._state.list_projects():
            self._codex.ensure_project_visible(project.project_id)
        for binding in self._state.list_bindings():
            if binding.project_id:
                self._codex.ensure_project_visible(binding.project_id)

    def _sync_loaded_threads_once(self) -> None:
        self._service.link_loaded_threads()

    def _targets_for_thread(self, codex_thread_id: str) -> list[Binding]:
        try:
            primary_binding = self._state.get_binding_by_thread(codex_thread_id)
        except KeyError:
            return self._state.list_mirror_bindings_for_thread(codex_thread_id)
        return [primary_binding, *self._state.list_mirror_bindings_for_thread(codex_thread_id)]

    def _binding_by_topic(self, chat_id: int, message_thread_id: int) -> Binding | None:
        binding = self._state.get_binding_by_topic(chat_id, message_thread_id)
        if binding is not None:
            return binding
        return self._state.get_mirror_binding_by_topic(chat_id, message_thread_id)

    def _is_primary_binding(self, binding: Binding) -> bool:
        try:
            primary_binding = self._state.get_binding_by_thread(binding.codex_thread_id)
        except KeyError:
            return False
        return (
            primary_binding.chat_id == binding.chat_id
            and primary_binding.message_thread_id == binding.message_thread_id
        )

    def _save_binding(self, binding: Binding) -> Binding:
        if self._is_primary_binding(binding):
            return self._state.create_binding(binding)
        return self._state.upsert_mirror_binding(binding)

    def _get_outbound_message_for_target(self, binding: Binding, event_id: str) -> OutboundMessage | None:
        if self._is_primary_binding(binding):
            return self._state.get_outbound_message(binding.codex_thread_id, event_id)
        return self._state.get_mirror_outbound_message(
            binding.codex_thread_id,
            event_id,
            chat_id=binding.chat_id,
            message_thread_id=binding.message_thread_id,
        )

    def _upsert_outbound_message_for_target(self, binding: Binding, outbound_message: OutboundMessage) -> None:
        if self._is_primary_binding(binding):
            self._state.upsert_outbound_message(outbound_message)
            return
        self._state.upsert_mirror_outbound_message(
            outbound_message,
            chat_id=binding.chat_id,
            message_thread_id=binding.message_thread_id,
        )

    def _has_seen_event_for_target(self, binding: Binding, event_id: str) -> bool:
        if self._is_primary_binding(binding):
            return self._state.has_seen_event(binding.codex_thread_id, event_id)
        return self._state.has_mirror_seen_event(
            binding.codex_thread_id,
            event_id,
            chat_id=binding.chat_id,
            message_thread_id=binding.message_thread_id,
        )

    def _mark_event_seen_for_target(self, binding: Binding, event_id: str) -> None:
        if self._is_primary_binding(binding):
            self._state.mark_event_seen(binding.codex_thread_id, event_id)
            return
        self._state.mark_mirror_event_seen(
            binding.codex_thread_id,
            event_id,
            chat_id=binding.chat_id,
            message_thread_id=binding.message_thread_id,
        )

    def _process_topic_creation_jobs(self) -> None:
        now = time.time()
        for topic_creation_job in self._state.list_topic_creation_jobs():
            if topic_creation_job.retry_after_at is not None and now < topic_creation_job.retry_after_at:
                continue
            thread = self._codex.read_thread(topic_creation_job.codex_thread_id)
            topic_name = format_topic_name(
                topic_creation_job.project_id or thread.cwd,
                thread.title,
            )
            try:
                message_thread_id = self._telegram.create_forum_topic(
                    topic_creation_job.chat_id,
                    topic_name,
                )
            except TelegramRetryAfterError as exc:
                self._state.upsert_topic_creation_job(
                    TopicCreationJob(
                        codex_thread_id=topic_creation_job.codex_thread_id,
                        chat_id=topic_creation_job.chat_id,
                        topic_name=topic_name,
                        project_id=topic_creation_job.project_id or thread.cwd or None,
                        retry_after_at=now + exc.retry_after_seconds + 1,
                    )
                )
                continue
            mirror_binding = Binding(
                codex_thread_id=topic_creation_job.codex_thread_id,
                chat_id=topic_creation_job.chat_id,
                message_thread_id=message_thread_id,
                topic_name=topic_name,
                sync_mode=self._config.sync_mode,
                project_id=topic_creation_job.project_id or thread.cwd or None,
                binding_status=ACTIVE_BINDING_STATUS,
            )
            self._state.upsert_mirror_binding(mirror_binding)
            for event in self._codex.list_events(topic_creation_job.codex_thread_id):
                self._state.mark_mirror_event_seen(
                    topic_creation_job.codex_thread_id,
                    event.event_id,
                    chat_id=mirror_binding.chat_id,
                    message_thread_id=mirror_binding.message_thread_id,
                )
            self._state.delete_topic_creation_job(topic_creation_job.codex_thread_id, topic_creation_job.chat_id)

    def _send_typing_if_due(self, chat_id: int, message_thread_id: int, *, force: bool = False) -> None:
        now = time.monotonic()
        key = (chat_id, message_thread_id)
        if not force:
            last_sent_at = self._last_typing_sent_at.get(key)
            if last_sent_at is not None and now - last_sent_at < self._TYPING_INTERVAL_SECONDS:
                return
        try:
            self._telegram.send_chat_action(chat_id, message_thread_id, self._TYPING_ACTION)
        except Exception:
            return
        self._last_typing_sent_at[key] = now

    def _clear_typing_state(self, chat_id: int, message_thread_id: int) -> None:
        self._last_typing_sent_at.pop((chat_id, message_thread_id), None)

    def run_lifecycle_sweeps(
        self,
        *,
        now_monotonic: float | None = None,
        now_epoch: float | None = None,
    ) -> None:
        monotonic_now = time.monotonic() if now_monotonic is None else now_monotonic
        epoch_now = time.time() if now_epoch is None else now_epoch

        if should_probe_topics(
            self._lifecycle_timers["probe"],
            now=monotonic_now,
            interval_seconds=self._config.lifecycle_probe_interval_seconds,
        ):
            self._lifecycle_timers["probe"] = monotonic_now
            self._probe_topic_existence()

        if should_probe_topics(
            self._lifecycle_timers["autoclose"],
            now=monotonic_now,
            interval_seconds=self._config.lifecycle_probe_interval_seconds,
        ):
            self._lifecycle_timers["autoclose"] = monotonic_now
            self._autoclose_completed_topics(epoch_now)

        if should_probe_topics(
            self._lifecycle_timers["unbound"],
            now=monotonic_now,
            interval_seconds=self._config.lifecycle_probe_interval_seconds,
        ):
            self._lifecycle_timers["unbound"] = monotonic_now
            self._expire_unbound_topics(epoch_now)

        if should_prune_state(
            self._lifecycle_timers["prune"],
            now=monotonic_now,
            interval_seconds=self._config.lifecycle_prune_interval_seconds,
        ):
            self._lifecycle_timers["prune"] = monotonic_now
            self._prune_stale_state()

    def _touch_topic_lifecycle(
        self,
        codex_thread_id: str,
        *,
        bound_at: float | None | object = _UNSET,
        last_inbound_at: float | None | object = _UNSET,
        last_outbound_at: float | None | object = _UNSET,
        completed_at: float | None | object = _UNSET,
    ) -> None:
        binding = self._state.get_binding_by_thread(codex_thread_id)
        existing = self._state.get_topic_lifecycle(codex_thread_id)
        resolved_bound_at = existing.bound_at if existing is not None else None
        if bound_at is not _UNSET:
            resolved_bound_at = bound_at
        if existing is None and bound_at is _UNSET:
            resolved_bound_at = time.time()
        resolved_last_inbound_at = existing.last_inbound_at if existing is not None else None
        if last_inbound_at is not _UNSET:
            resolved_last_inbound_at = last_inbound_at
        resolved_last_outbound_at = existing.last_outbound_at if existing is not None else None
        if last_outbound_at is not _UNSET:
            resolved_last_outbound_at = last_outbound_at
        resolved_completed_at = existing.completed_at if existing is not None else None
        if completed_at is not _UNSET:
            resolved_completed_at = completed_at
        topic_lifecycle = TopicLifecycle(
            codex_thread_id=codex_thread_id,
            chat_id=binding.chat_id,
            message_thread_id=binding.message_thread_id,
            bound_at=resolved_bound_at,
            last_inbound_at=resolved_last_inbound_at,
            last_outbound_at=resolved_last_outbound_at,
            completed_at=resolved_completed_at,
        )
        self._state.upsert_topic_lifecycle(topic_lifecycle)

    def _mark_topic_completed(self, codex_thread_id: str) -> None:
        self._touch_topic_lifecycle(codex_thread_id, completed_at=time.time())

    def _probe_topic_existence(self) -> None:
        for binding in [*self._state.list_bindings(), *self._state.list_mirror_bindings()]:
            if binding.binding_status == DELETED_BINDING_STATUS:
                continue
            if self._telegram.probe_topic(binding.chat_id, binding.message_thread_id):
                continue
            self._save_binding(
                replace(
                    binding,
                    binding_status=DELETED_BINDING_STATUS,
                )
            )
            if self._is_primary_binding(binding):
                self._state.delete_topic_lifecycle(binding.codex_thread_id)
            self._clear_topic_status_override(binding.chat_id, binding.message_thread_id)
            self._clear_typing_state(binding.chat_id, binding.message_thread_id)

    def _autoclose_completed_topics(self, now_epoch: float) -> None:
        for topic_lifecycle in self._state.list_topic_lifecycles():
            if not should_autoclose_topic(
                topic_lifecycle,
                now=now_epoch,
                timeout_seconds=self._config.lifecycle_autoclose_after_seconds,
            ):
                continue
            binding = self._state.get_binding_by_thread(topic_lifecycle.codex_thread_id)
            if binding.binding_status != ACTIVE_BINDING_STATUS:
                continue
            if self._state.get_pending_turn(topic_lifecycle.codex_thread_id) is not None:
                continue
            try:
                self._telegram.close_forum_topic(binding.chat_id, binding.message_thread_id)
            except Exception as exc:
                if not self._mark_binding_deleted_if_missing_topic(binding, exc):
                    raise
                continue
            self._save_binding(
                replace(
                    binding,
                    binding_status=CLOSED_BINDING_STATUS,
                )
            )
            self._clear_typing_state(binding.chat_id, binding.message_thread_id)

    def _expire_unbound_topics(self, now_epoch: float) -> None:
        live_topic_keys = {
            (binding.chat_id, binding.message_thread_id)
            for binding in self._state.list_bindings()
            if binding.binding_status != DELETED_BINDING_STATUS
        }
        for chat_id, message_thread_id, last_seen_at in self._state.list_topic_project_last_seen():
            if (chat_id, message_thread_id) in live_topic_keys:
                continue
            if not is_unbound_topic_expired(
                last_seen_at,
                now=now_epoch,
                ttl_seconds=self._config.lifecycle_unbound_ttl_seconds,
            ):
                continue
            try:
                self._telegram.close_forum_topic(chat_id, message_thread_id)
            except Exception as exc:
                if not is_missing_topic_error(exc):
                    raise
            self._state.delete_topic_project(chat_id, message_thread_id)
            self._state.delete_topic_project_last_seen(chat_id, message_thread_id)

    def _prune_stale_state(self) -> None:
        live_topics = {
            (binding.chat_id, binding.message_thread_id)
            for binding in [*self._state.list_bindings(), *self._state.list_mirror_bindings()]
            if binding.binding_status != DELETED_BINDING_STATUS
        }
        live_topics.update(
            (topic_project.chat_id, topic_project.message_thread_id)
            for topic_project in (
                self._state.get_topic_project(chat_id, message_thread_id)
                for chat_id, message_thread_id, _ in self._state.list_topic_project_last_seen()
            )
            if topic_project is not None
        )
        self._state.prune_orphan_topic_history(live_topics)

    def _set_topic_status_override(self, chat_id: int, message_thread_id: int, status: str) -> None:
        self._topic_status_overrides[(chat_id, message_thread_id)] = status

    def _clear_topic_status_override(self, chat_id: int, message_thread_id: int) -> None:
        self._topic_status_overrides.pop((chat_id, message_thread_id), None)

    def _topic_status_for_binding(
        self,
        binding: Binding,
        pending_turn: PendingTurn | None,
        turn_result: TurnResult | None = None,
    ) -> str:
        key = (binding.chat_id, binding.message_thread_id)
        if binding.binding_status == CLOSED_BINDING_STATUS:
            return TOPIC_STATUS_CLOSED
        if pending_turn is not None:
            self._clear_topic_status_override(*key)
            if turn_result is not None and turn_result.waiting_for_approval:
                return TOPIC_STATUS_APPROVAL
            if turn_result is not None and _is_terminal_turn_status(turn_result.status):
                if turn_result.status == "completed":
                    return TOPIC_STATUS_IDLE
                return TOPIC_STATUS_FAILED
            return TOPIC_STATUS_RUNNING
        return self._topic_status_overrides.get(key, TOPIC_STATUS_IDLE)

    def _desired_topic_name(
        self,
        binding: Binding,
        *,
        base_topic_name: str,
        topic_status: str,
    ) -> str:
        emoji_enabled = (
            self._config.telegram_topic_status_emoji_enabled
            and binding.chat_id not in self._topic_status_disabled_chats
        )
        return format_topic_title_for_status(
            base_topic_name,
            topic_status,
            emoji_enabled=emoji_enabled,
        )

    def _sync_topic_name(
        self,
        binding: Binding,
        *,
        desired_topic_name: str,
        base_topic_name: str,
    ) -> Binding:
        try:
            self._telegram.edit_forum_topic(
                binding.chat_id,
                binding.message_thread_id,
                desired_topic_name,
            )
        except Exception as exc:
            if (
                desired_topic_name != base_topic_name
                and is_topic_edit_permission_error(exc)
            ):
                self._topic_status_disabled_chats.add(binding.chat_id)
                return binding
            if self._mark_binding_deleted_if_missing_topic(binding, exc):
                return self._binding_by_topic(binding.chat_id, binding.message_thread_id) or binding
            raise
        return self._save_binding(replace(binding, topic_name=desired_topic_name))

    def _topic_name_matches_desired(
        self,
        binding: Binding,
        *,
        desired_topic_name: str,
        base_topic_name: str,
    ) -> bool:
        if binding.topic_name == desired_topic_name:
            return True
        if (
            desired_topic_name == base_topic_name
            and binding.chat_id in self._topic_status_disabled_chats
            and binding.topic_name is not None
        ):
            return strip_topic_status_prefix(binding.topic_name) == base_topic_name
        return False

    def _send_message_parts(
        self,
        chat_id: int,
        message_thread_id: int,
        text: str,
        *,
        reply_markup: dict[str, object] | None = None,
    ) -> tuple[int, ...]:
        message_ids = tuple(
            self._telegram.send_message(chat_id, message_thread_id, part)
            for part in _split_outbound_text(text, self._TELEGRAM_MESSAGE_LIMIT)
        )
        self._sync_last_reply_markup(
            chat_id,
            previous_message_ids=(),
            next_message_ids=message_ids,
            previous_reply_markup=None,
            next_reply_markup=reply_markup,
        )
        return message_ids

    def _sync_message_parts(
        self,
        chat_id: int,
        message_thread_id: int,
        message_ids: tuple[int, ...],
        previous_text: str,
        next_text: str,
        *,
        previous_reply_markup: dict[str, object] | None,
        next_reply_markup: dict[str, object] | None,
    ) -> tuple[int, ...]:
        previous_parts = _split_outbound_text(previous_text, self._TELEGRAM_MESSAGE_LIMIT)
        next_parts = _split_outbound_text(next_text, self._TELEGRAM_MESSAGE_LIMIT)
        next_message_ids = list(message_ids)

        common_count = min(len(previous_parts), len(next_parts), len(next_message_ids))
        for index in range(common_count):
            if previous_parts[index] == next_parts[index]:
                continue
            self._telegram.edit_message_text(
                chat_id,
                next_message_ids[index],
                next_parts[index],
            )

        for part in next_parts[len(next_message_ids) :]:
            next_message_ids.append(self._telegram.send_message(chat_id, message_thread_id, part))

        next_message_ids_tuple = tuple(next_message_ids)
        self._sync_last_reply_markup(
            chat_id,
            previous_message_ids=message_ids,
            next_message_ids=next_message_ids_tuple,
            previous_reply_markup=previous_reply_markup,
            next_reply_markup=next_reply_markup,
        )
        return next_message_ids_tuple

    def _sync_last_reply_markup(
        self,
        chat_id: int,
        *,
        previous_message_ids: tuple[int, ...],
        next_message_ids: tuple[int, ...],
        previous_reply_markup: dict[str, object] | None,
        next_reply_markup: dict[str, object] | None,
    ) -> None:
        previous_last_id = previous_message_ids[-1] if previous_message_ids else None
        next_last_id = next_message_ids[-1] if next_message_ids else None

        if previous_last_id == next_last_id:
            if next_last_id is None or previous_reply_markup == next_reply_markup:
                return
            self._telegram.edit_message_reply_markup(chat_id, next_last_id, next_reply_markup)
            return

        if previous_last_id is not None and previous_reply_markup is not None:
            self._telegram.edit_message_reply_markup(chat_id, previous_last_id, None)
        if next_last_id is not None and next_reply_markup is not None:
            self._telegram.edit_message_reply_markup(chat_id, next_last_id, next_reply_markup)

    def _assistant_reply_markup(
        self,
        binding: Binding,
        active_turn_result: TurnResult | None,
    ) -> dict[str, object]:
        if active_turn_result is None:
            status = "ready"
        elif active_turn_result.waiting_for_approval:
            status = "approval"
        elif not _is_terminal_turn_status(active_turn_result.status):
            status = "running"
        elif active_turn_result.status == "completed":
            status = "ready"
        else:
            status = active_turn_result.status
        history = self._state.list_topic_history(binding.chat_id, binding.message_thread_id, limit=2)
        return _response_widget_markup(status=status, history=history)

    def _record_topic_created(self, update: dict[str, object]) -> None:
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        if self._binding_by_topic(chat_id, message_thread_id) is not None:
            return
        existing = self._state.get_topic_project(chat_id, message_thread_id)
        self._state.upsert_topic_project(
            TopicProject(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                topic_name=str(update.get("topic_name") or (existing.topic_name if existing else "") or ""),
                project_id=existing.project_id if existing else None,
                picker_message_id=existing.picker_message_id if existing else None,
                pending_update_id=existing.pending_update_id if existing else None,
                pending_user_id=existing.pending_user_id if existing else None,
                pending_text=existing.pending_text if existing else None,
                pending_local_image_paths=existing.pending_local_image_paths if existing else (),
                browse_path=existing.browse_path if existing else None,
                browse_page=existing.browse_page if existing else 0,
            )
        )
        self._state.set_topic_project_last_seen(chat_id, message_thread_id, time.time())

    def _handle_topic_closed(self, update: dict[str, object]) -> None:
        binding = self._binding_by_topic(
            int(update["chat_id"]),
            int(update["message_thread_id"]),
        )
        if binding is None or binding.binding_status == CLOSED_BINDING_STATUS:
            return
        self._save_binding(
            replace(
                binding,
                binding_status=CLOSED_BINDING_STATUS,
            )
        )
        self._clear_typing_state(binding.chat_id, binding.message_thread_id)

    def _handle_topic_reopened(self, update: dict[str, object]) -> None:
        binding = self._binding_by_topic(
            int(update["chat_id"]),
            int(update["message_thread_id"]),
        )
        if binding is None or binding.binding_status == ACTIVE_BINDING_STATUS:
            return
        self._save_binding(
            replace(
                binding,
                binding_status=ACTIVE_BINDING_STATUS,
            )
        )
        if self._is_primary_binding(binding) and self._state.get_topic_lifecycle(binding.codex_thread_id) is not None:
            self._touch_topic_lifecycle(binding.codex_thread_id, completed_at=None)
        self._clear_topic_status_override(binding.chat_id, binding.message_thread_id)

    def _handle_topic_edited(self, update: dict[str, object]) -> None:
        binding = self._binding_by_topic(
            int(update["chat_id"]),
            int(update["message_thread_id"]),
        )
        if binding is None or binding.binding_status != ACTIVE_BINDING_STATUS:
            return

        raw_name = str(update.get("topic_name") or "").strip()
        if not raw_name or raw_name == (binding.topic_name or ""):
            return

        thread = self._codex.read_thread(binding.codex_thread_id)
        project_id = binding.project_id or thread.cwd
        topic_status = self._topic_status_for_binding(
            binding,
            self._state.get_pending_turn(binding.codex_thread_id),
        )
        desired_topic_name = self._desired_topic_name(
            binding,
            base_topic_name=format_topic_name(project_id, thread.title),
            topic_status=topic_status,
        )
        canonical_name = format_topic_name(project_id, thread.title)
        new_name = strip_topic_status_prefix(raw_name)
        if new_name == canonical_name:
            binding = self._save_binding(replace(binding, topic_name=desired_topic_name))
            if raw_name != desired_topic_name:
                self._sync_topic_name(
                    binding,
                    desired_topic_name=desired_topic_name,
                    base_topic_name=canonical_name,
                )
            return

        parsed_name = _parse_topic_name(new_name)
        expected_project_name = Path(project_id).name.strip()
        is_authorized_rename = int(update["from_user_id"]) in self._config.telegram_allowed_user_ids
        if (
            is_authorized_rename
            and parsed_name is not None
            and parsed_name[0] == expected_project_name
            and parsed_name[1] != thread.title
        ):
            renamed_thread = self._codex.rename_thread(binding.codex_thread_id, parsed_name[1])
            desired_topic_name = self._desired_topic_name(
                binding,
                base_topic_name=format_topic_name(project_id, renamed_thread.title),
                topic_status=topic_status,
            )
            self._save_binding(replace(binding, topic_name=desired_topic_name))
            if desired_topic_name != raw_name:
                self._sync_topic_name(
                    binding,
                    desired_topic_name=desired_topic_name,
                    base_topic_name=format_topic_name(project_id, renamed_thread.title),
                )
            return

        self._sync_topic_name(
            binding,
            desired_topic_name=desired_topic_name,
            base_topic_name=canonical_name,
        )

    def _mark_binding_deleted_if_missing_topic(self, binding: Binding, exc: Exception) -> bool:
        if not is_missing_topic_error(exc):
            return False
        self._save_binding(
            replace(
                binding,
                binding_status=DELETED_BINDING_STATUS,
            )
        )
        if self._is_primary_binding(binding):
            self._state.delete_topic_lifecycle(binding.codex_thread_id)
        self._clear_topic_status_override(binding.chat_id, binding.message_thread_id)
        self._clear_typing_state(binding.chat_id, binding.message_thread_id)
        return True

    def _handle_unbound_topic_message(self, update: dict[str, object]) -> None:
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        from_user_id = int(update["from_user_id"])
        text = str(update.get("text") or "")
        local_image_paths = _normalized_local_image_paths(update)
        topic_project = self._state.get_topic_project(chat_id, message_thread_id)

        if topic_project is not None and topic_project.picker_message_id is not None:
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                "Use the project picker above to choose an existing project or browse folders.",
            )
            return
        self._open_project_picker(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            topic_name=topic_project.topic_name if topic_project else None,
            pending_update_id=int(update["update_id"]),
            pending_user_id=from_user_id,
            pending_text=text,
            pending_local_image_paths=local_image_paths,
        )

    def _handle_callback_query(self, update: dict[str, object]) -> None:
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        callback_query_id = str(update["callback_query_id"])
        data = str(update["data"])

        if data == _CALLBACK_NOOP:
            self._telegram.answer_callback_query(callback_query_id)
            return
        if data.startswith(CALLBACK_HISTORY_PREFIX):
            self._handle_history_callback(update)
            return
        if data.startswith("gw:restore:"):
            self._handle_restore_callback(update)
            return
        if data.startswith(CALLBACK_RESUME_PAGE_PREFIX) or data.startswith(CALLBACK_RESUME_PICK_PREFIX) or data == CALLBACK_RESUME_CANCEL:
            self._handle_resume_callback(update)
            return
        if data.startswith(_CALLBACK_SYNC_PREFIX):
            self._handle_sync_callback(update)
            return
        if data.startswith(_CALLBACK_SESSIONS_PREFIX):
            self._handle_sessions_callback(update)
            return
        if data.startswith(_CALLBACK_QUEUE_PREFIX):
            self._handle_queue_callback(update)
            return
        if data.startswith(_CALLBACK_RESPONSE_PREFIX):
            self._handle_response_callback(update)
            return

        topic_project = self._state.get_topic_project(chat_id, message_thread_id)
        if topic_project is None:
            self._telegram.answer_callback_query(callback_query_id, "This picker is no longer active.")
            return

        message_id = int(update["message_id"])
        if topic_project.picker_message_id is not None and message_id != topic_project.picker_message_id:
            self._telegram.answer_callback_query(callback_query_id, "This picker is stale.")
            return

        if data == _CALLBACK_BROWSE_OPEN:
            self._show_folder_browser(
                TopicProject(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    topic_name=topic_project.topic_name,
                    project_id=topic_project.project_id,
                    picker_message_id=topic_project.picker_message_id,
                    pending_update_id=topic_project.pending_update_id,
                    pending_user_id=topic_project.pending_user_id,
                    pending_text=topic_project.pending_text,
                    pending_local_image_paths=topic_project.pending_local_image_paths,
                    browse_path=str(_browser_home_path()),
                    browse_page=0,
                )
            )
            self._telegram.answer_callback_query(callback_query_id)
            return
        if data == _CALLBACK_BROWSE_BACK:
            self._show_project_picker(
                TopicProject(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    topic_name=topic_project.topic_name,
                    project_id=topic_project.project_id,
                    picker_message_id=topic_project.picker_message_id,
                    pending_update_id=topic_project.pending_update_id,
                    pending_user_id=topic_project.pending_user_id,
                    pending_text=topic_project.pending_text,
                    pending_local_image_paths=topic_project.pending_local_image_paths,
                    browse_path=None,
                    browse_page=0,
                )
            )
            self._telegram.answer_callback_query(callback_query_id)
            return
        if data == _CALLBACK_CANCEL:
            if topic_project.picker_message_id is not None:
                self._telegram.edit_message_reply_markup(chat_id, topic_project.picker_message_id, None)
            self._state.delete_topic_project(chat_id, message_thread_id)
            self._telegram.answer_callback_query(callback_query_id, "Cancelled.")
            return
        if data == _CALLBACK_BROWSE_SELECT:
            browse_path = Path(topic_project.browse_path or str(_browser_home_path()))
            self._state.upsert_project(
                CodexProject(
                    project_id=str(browse_path),
                    project_name=browse_path.name or str(browse_path),
                )
            )
            self._bind_topic_project(
                TopicProject(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    topic_name=topic_project.topic_name,
                    project_id=str(browse_path),
                    picker_message_id=topic_project.picker_message_id,
                    pending_update_id=topic_project.pending_update_id,
                    pending_user_id=topic_project.pending_user_id,
                    pending_text=topic_project.pending_text,
                    pending_local_image_paths=topic_project.pending_local_image_paths,
                    browse_path=str(browse_path),
                    browse_page=topic_project.browse_page,
                )
            )
            self._telegram.answer_callback_query(callback_query_id, f"Selected {browse_path.name or browse_path}.")
            return
        if data == _CALLBACK_BROWSE_HOME:
            self._show_folder_browser(
                TopicProject(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    topic_name=topic_project.topic_name,
                    project_id=topic_project.project_id,
                    picker_message_id=topic_project.picker_message_id,
                    pending_update_id=topic_project.pending_update_id,
                    pending_user_id=topic_project.pending_user_id,
                    pending_text=topic_project.pending_text,
                    pending_local_image_paths=topic_project.pending_local_image_paths,
                    browse_path=str(_browser_home_path()),
                    browse_page=0,
                )
            )
            self._telegram.answer_callback_query(callback_query_id)
            return
        if data == _CALLBACK_BROWSE_UP:
            current_path = Path(topic_project.browse_path or str(_browser_home_path()))
            next_path = current_path.parent if current_path.parent != current_path else current_path
            self._show_folder_browser(
                TopicProject(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    topic_name=topic_project.topic_name,
                    project_id=topic_project.project_id,
                    picker_message_id=topic_project.picker_message_id,
                    pending_update_id=topic_project.pending_update_id,
                    pending_user_id=topic_project.pending_user_id,
                    pending_text=topic_project.pending_text,
                    pending_local_image_paths=topic_project.pending_local_image_paths,
                    browse_path=str(next_path),
                    browse_page=0,
                )
            )
            self._telegram.answer_callback_query(callback_query_id)
            return
        if data.startswith(_CALLBACK_BROWSE_PAGE_PREFIX):
            try:
                browse_page = int(data[len(_CALLBACK_BROWSE_PAGE_PREFIX):])
            except ValueError:
                self._telegram.answer_callback_query(callback_query_id, "Invalid page.")
                return
            self._show_folder_browser(
                TopicProject(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    topic_name=topic_project.topic_name,
                    project_id=topic_project.project_id,
                    picker_message_id=topic_project.picker_message_id,
                    pending_update_id=topic_project.pending_update_id,
                    pending_user_id=topic_project.pending_user_id,
                    pending_text=topic_project.pending_text,
                    pending_local_image_paths=topic_project.pending_local_image_paths,
                    browse_path=topic_project.browse_path or str(_browser_home_path()),
                    browse_page=browse_page,
                )
            )
            self._telegram.answer_callback_query(callback_query_id)
            return
        if data.startswith(_CALLBACK_BROWSE_ENTER_PREFIX):
            try:
                directory_index = int(data[len(_CALLBACK_BROWSE_ENTER_PREFIX):])
            except ValueError:
                self._telegram.answer_callback_query(callback_query_id, "Invalid folder.")
                return
            current_path = Path(topic_project.browse_path or str(_browser_home_path()))
            directories = _list_subdirectories(current_path)
            if directory_index < 0 or directory_index >= len(directories):
                self._telegram.answer_callback_query(callback_query_id, "Folder list changed. Try again.")
                return
            self._show_folder_browser(
                TopicProject(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    topic_name=topic_project.topic_name,
                    project_id=topic_project.project_id,
                    picker_message_id=topic_project.picker_message_id,
                    pending_update_id=topic_project.pending_update_id,
                    pending_user_id=topic_project.pending_user_id,
                    pending_text=topic_project.pending_text,
                    pending_local_image_paths=topic_project.pending_local_image_paths,
                    browse_path=str(directories[directory_index]),
                    browse_page=0,
                )
            )
            self._telegram.answer_callback_query(callback_query_id)
            return
        if not data.startswith(_CALLBACK_PROJECT_PREFIX):
            self._telegram.answer_callback_query(callback_query_id, "Unknown picker action.")
            return

        try:
            project_index = int(data[len(_CALLBACK_PROJECT_PREFIX):])
        except ValueError:
            self._telegram.answer_callback_query(callback_query_id, "Invalid project selection.")
            return
        projects = self._state.list_projects()
        if project_index < 0 or project_index >= len(projects):
            self._telegram.answer_callback_query(callback_query_id, "Project list changed. Open the picker again.")
            return

        project = projects[project_index]
        self._bind_topic_project(
            TopicProject(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                topic_name=topic_project.topic_name,
                project_id=project.project_id,
                picker_message_id=topic_project.picker_message_id,
                pending_update_id=topic_project.pending_update_id,
                pending_user_id=topic_project.pending_user_id,
                pending_text=topic_project.pending_text,
                pending_local_image_paths=topic_project.pending_local_image_paths,
                browse_path=topic_project.browse_path,
                browse_page=topic_project.browse_page,
            )
        )
        self._telegram.answer_callback_query(callback_query_id, f"Selected {project.project_name}.")

    def _handle_sync_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_id = int(update["message_id"])
        data = str(update["data"])

        if data == _CALLBACK_SYNC_DISMISS:
            self._telegram.edit_message_reply_markup(chat_id, message_id, None)
            self._telegram.answer_callback_query(callback_query_id, "Dismissed.")
            return

        if data != _CALLBACK_SYNC_FIX:
            self._telegram.answer_callback_query(callback_query_id, "Unknown sync action.")
            return

        audit = self._audit_sync_state()
        fixed_count = 0
        for thread in audit.unbound_loaded_threads:
            self._service.link_thread(thread.thread_id)
            fixed_count += 1
        for binding in audit.dead_topics:
            self._service.recreate_topic(binding.codex_thread_id)
            fixed_count += 1

        refreshed_audit = self._audit_sync_state()
        self._telegram.edit_message_text(
            chat_id,
            message_id,
            _sync_report_text(refreshed_audit, fixed_count=fixed_count),
            reply_markup=_sync_report_markup(refreshed_audit),
        )
        self._telegram.answer_callback_query(callback_query_id, f"Fixed {fixed_count} issue(s).")

    def _handle_sessions_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_id = int(update["message_id"])
        data = str(update["data"])

        if data == _CALLBACK_SESSIONS_DISMISS:
            self._telegram.edit_message_reply_markup(chat_id, message_id, None)
            self._telegram.answer_callback_query(callback_query_id, "Dismissed.")
            return
        if data != _CALLBACK_SESSIONS_REFRESH:
            self._telegram.answer_callback_query(callback_query_id, "Unknown sessions action.")
            return

        self._telegram.edit_message_text(
            chat_id,
            message_id,
            self._bindings_dashboard_text(),
            reply_markup=_sessions_dashboard_markup(),
        )
        self._telegram.answer_callback_query(callback_query_id, "Refreshed.")

    def _handle_history_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        parsed_callback = parse_history_callback(str(update["data"]))
        if parsed_callback is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown history action.")
            return

        page_index, thread_id = parsed_callback
        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is None or binding.codex_thread_id != thread_id:
            self._telegram.answer_callback_query(callback_query_id, "This topic is no longer bound.")
            return

        history_view = self._state.get_history_view(chat_id, message_thread_id)
        if history_view is None or history_view.message_id != message_id:
            self._telegram.answer_callback_query(callback_query_id, "This history view is stale.")
            return
        if history_view.codex_thread_id != thread_id:
            self._telegram.answer_callback_query(callback_query_id, "This history view no longer matches the topic.")
            return

        self._show_history_message(binding, page_index=page_index, message_id=message_id)
        self._telegram.answer_callback_query(callback_query_id, "Page updated.")

    def _handle_restore_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        data = str(update["data"])
        binding = self._binding_by_topic(chat_id, message_thread_id)
        restore_view = self._state.get_restore_view(chat_id, message_thread_id)

        if data == CALLBACK_RESTORE_CANCEL:
            if restore_view is not None and restore_view.message_id == message_id:
                self._telegram.edit_message_reply_markup(chat_id, message_id, None)
                self._state.delete_restore_view(chat_id, message_thread_id)
            self._telegram.answer_callback_query(callback_query_id, "Cancelled.")
            return

        if binding is None or not self._is_primary_binding(binding):
            self._telegram.answer_callback_query(callback_query_id, "This topic is no longer eligible for recovery.")
            return
        if restore_view is None or restore_view.message_id != message_id:
            self._telegram.answer_callback_query(callback_query_id, "This recovery menu is stale.")
            return
        if restore_view.codex_thread_id != binding.codex_thread_id:
            self._telegram.answer_callback_query(callback_query_id, "This recovery menu no longer matches the topic.")
            return

        issue_kind = self._restore_issue_for_binding(binding)
        if issue_kind is None:
            self._state.delete_restore_view(chat_id, message_thread_id)
            self._telegram.edit_message_text(
                chat_id,
                message_id,
                "Nothing to restore. This topic is already healthy.",
                reply_markup=None,
            )
            self._telegram.answer_callback_query(callback_query_id, "Already healthy.")
            return
        if issue_kind != restore_view.issue_kind:
            self._offer_restore_prompt(binding, message_id=message_id)
            self._telegram.answer_callback_query(callback_query_id, "Recovery state changed. Refreshed.")
            return

        if data == CALLBACK_RESTORE_CONTINUE:
            if issue_kind != RESTORE_ISSUE_CLOSED:
                self._telegram.answer_callback_query(callback_query_id, "Continue here is not available for this issue.")
                return
            thread = self._codex.read_thread(binding.codex_thread_id)
            topic_name = format_topic_name(binding.project_id or thread.cwd, thread.title)
            try:
                self._telegram.edit_forum_topic(chat_id, message_thread_id, topic_name)
            except Exception as exc:
                if not is_topic_edit_permission_error(exc):
                    if self._mark_binding_deleted_if_missing_topic(binding, exc):
                        self._telegram.answer_callback_query(callback_query_id, "This topic is no longer reachable.")
                        return
                    raise
            restored_binding = self._save_binding(
                replace(
                    binding,
                    topic_name=topic_name,
                    binding_status=ACTIVE_BINDING_STATUS,
                )
            )
            self._touch_topic_lifecycle(restored_binding.codex_thread_id, completed_at=None)
            self._clear_topic_status_override(chat_id, message_thread_id)
            self._state.delete_restore_view(chat_id, message_thread_id)
            self._telegram.edit_message_text(
                chat_id,
                message_id,
                (
                    "Restored this topic in place.\n"
                    f"Thread id: `{restored_binding.codex_thread_id}`"
                ),
                reply_markup=None,
            )
            self._telegram.answer_callback_query(callback_query_id, "Restored.")
            return

        if data == CALLBACK_RESTORE_RECREATE:
            if issue_kind != RESTORE_ISSUE_DELETED:
                self._telegram.answer_callback_query(callback_query_id, "Recreate is not available for this issue.")
                return
            recreated = self._service.recreate_topic(binding.codex_thread_id)
            self._state.delete_restore_view(chat_id, message_thread_id)
            self._telegram.edit_message_text(
                chat_id,
                message_id,
                (
                    "Recreated the Telegram topic for this Codex thread.\n"
                    f"New topic id: `{recreated.message_thread_id}`\n"
                    f"Thread id: `{recreated.codex_thread_id}`"
                ),
                reply_markup=None,
            )
            self._telegram.answer_callback_query(callback_query_id, "Recreated.")
            return

        if data == CALLBACK_RESTORE_RESUME:
            self._state.delete_restore_view(chat_id, message_thread_id)
            self._open_resume_picker(binding, message_id=message_id)
            self._telegram.answer_callback_query(callback_query_id, "Choose a thread.")
            return

        self._telegram.answer_callback_query(callback_query_id, "Unknown recovery action.")

    def _handle_resume_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        data = str(update["data"])
        binding = self._binding_by_topic(chat_id, message_thread_id)
        resume_view = self._state.get_resume_view(chat_id, message_thread_id)

        if data == CALLBACK_RESUME_CANCEL:
            if resume_view is not None and resume_view.message_id == message_id:
                self._telegram.edit_message_reply_markup(chat_id, message_id, None)
                self._state.delete_resume_view(chat_id, message_thread_id)
            self._telegram.answer_callback_query(callback_query_id, "Cancelled.")
            return

        if binding is None or not self._is_primary_binding(binding):
            self._telegram.answer_callback_query(callback_query_id, "This topic is no longer eligible for resume.")
            return
        if resume_view is None or resume_view.message_id != message_id:
            self._telegram.answer_callback_query(callback_query_id, "This resume picker is stale.")
            return

        project_id = binding.project_id or self._codex.read_thread(binding.codex_thread_id).cwd
        if project_id != resume_view.project_id:
            self._telegram.answer_callback_query(callback_query_id, "This resume picker no longer matches the topic.")
            return

        page_index = parse_resume_page_callback(data)
        if page_index is not None:
            self._open_resume_picker(binding, page_index=page_index, message_id=message_id)
            self._telegram.answer_callback_query(callback_query_id, "Page updated.")
            return

        picked_thread_id = parse_resume_pick_callback(data)
        if picked_thread_id is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown resume action.")
            return

        resumable_threads = self._codex.list_resumable_threads(
            project_id,
            exclude_thread_id=binding.codex_thread_id,
        )
        target_thread = next(
            (thread for thread in resumable_threads if thread.thread_id == picked_thread_id),
            None,
        )
        if target_thread is None:
            self._telegram.answer_callback_query(callback_query_id, "That thread is no longer available.")
            return

        previous_thread_id = binding.codex_thread_id
        rebound_binding = self._service.rebind_topic_to_thread(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            codex_thread_id=picked_thread_id,
        )
        self._state.delete_pending_turn(previous_thread_id)
        self._state.delete_topic_lifecycle(previous_thread_id)
        self._state.delete_history_view(chat_id, message_thread_id)
        self._state.delete_resume_view(chat_id, message_thread_id)
        self._state.delete_restore_view(chat_id, message_thread_id)
        self._clear_typing_state(chat_id, message_thread_id)
        self._clear_topic_status_override(chat_id, message_thread_id)
        self._telegram.edit_message_text(
            chat_id,
            message_id,
            (
                f"Resumed this topic into `{target_thread.title}`.\n"
                f"Thread id: `{rebound_binding.codex_thread_id}`"
            ),
            reply_markup=None,
        )
        self._telegram.answer_callback_query(callback_query_id, "Resumed.")

    def _handle_queue_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        data = str(update["data"])

        if not data.startswith(_CALLBACK_QUEUE_STEER_PREFIX):
            self._telegram.answer_callback_query(callback_query_id, "Unknown queue action.")
            return

        try:
            telegram_update_id = int(data[len(_CALLBACK_QUEUE_STEER_PREFIX):])
        except ValueError:
            self._telegram.answer_callback_query(callback_query_id, "Invalid queued message.")
            return

        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is None:
            self._telegram.edit_message_reply_markup(chat_id, message_id, None)
            self._telegram.answer_callback_query(callback_query_id, "This topic is no longer bound.")
            return

        queued_message = self._queued_inbound_message(telegram_update_id, binding.codex_thread_id)
        if queued_message is None:
            self._telegram.edit_message_reply_markup(chat_id, message_id, None)
            self._telegram.answer_callback_query(callback_query_id, "This message is no longer queued.")
            return

        pending_turn = self._state.get_pending_turn(binding.codex_thread_id)
        if pending_turn is None:
            self._telegram.edit_message_reply_markup(chat_id, message_id, None)
            self._telegram.answer_callback_query(
                callback_query_id,
                "Codex is no longer answering. This message stays queued.",
            )
            return

        self._send_typing_if_due(chat_id, message_thread_id, force=True)
        try:
            self._codex.steer_turn(
                StartedTurn(
                    thread_id=binding.codex_thread_id,
                    text=queued_message.text,
                    local_image_paths=queued_message.local_image_paths,
                ),
                expected_turn_id=pending_turn.turn_id,
                on_progress=lambda: self._send_typing_if_due(chat_id, message_thread_id),
            )
        except Exception as exc:
            if _is_terminal_steer_error(exc):
                self._telegram.edit_message_reply_markup(chat_id, message_id, None)
            self._telegram.answer_callback_query(
                callback_query_id,
                _steer_callback_text(exc),
            )
            return

        self._state.mark_inbound_delivered(queued_message.telegram_update_id)
        self._telegram.edit_message_reply_markup(chat_id, message_id, None)
        self._telegram.answer_callback_query(callback_query_id, "Steered.")

    def _handle_response_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        from_user_id = int(update["from_user_id"])
        data = str(update["data"])

        if data == _CALLBACK_RESPONSE_NOOP:
            self._telegram.answer_callback_query(callback_query_id)
            return

        binding = self._binding_by_topic(chat_id, message_thread_id)
        if data.startswith(_CALLBACK_RESPONSE_RECALL_PREFIX):
            if binding is None:
                self._telegram.answer_callback_query(callback_query_id, "This topic is no longer bound.")
                return
            try:
                history_index = int(data[len(_CALLBACK_RESPONSE_RECALL_PREFIX):])
            except ValueError:
                self._telegram.answer_callback_query(callback_query_id, "Invalid recall item.")
                return
            history = self._state.list_topic_history(chat_id, message_thread_id, limit=history_index + 1)
            if history_index < 0 or history_index >= len(history):
                self._telegram.answer_callback_query(callback_query_id, "That message is no longer available.")
                return
            recalled = history[history_index]
            self._enqueue_bound_inbound(
                binding,
                telegram_update_id=int(update["update_id"]),
                from_user_id=from_user_id,
                text=recalled.text,
                local_image_paths=recalled.local_image_paths,
            )
            self._telegram.answer_callback_query(callback_query_id, "Queued.")
            return

        if data == _CALLBACK_RESPONSE_NEW:
            if binding is not None and not self._is_primary_binding(binding):
                self._telegram.answer_callback_query(callback_query_id, _mirror_control_text())
                return
            if self._start_new_thread(chat_id, message_thread_id, binding, thread_title=DEFAULT_NEW_THREAD_TITLE):
                self._telegram.answer_callback_query(callback_query_id, "Started a new thread.")
            else:
                self._telegram.answer_callback_query(callback_query_id, "Select a project first.")
            return

        if data == _CALLBACK_RESPONSE_PROJECT:
            if binding is not None and not self._is_primary_binding(binding):
                self._telegram.answer_callback_query(callback_query_id, _mirror_control_text())
                return
            self._open_project_picker(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                topic_name=self._topic_name_for_command(chat_id, message_thread_id),
            )
            self._telegram.answer_callback_query(callback_query_id)
            return

        if data == _CALLBACK_RESPONSE_STATUS:
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                self._status_text(binding, chat_id, message_thread_id),
            )
            self._telegram.answer_callback_query(callback_query_id)
            return

        if data == _CALLBACK_RESPONSE_SYNC:
            audit = self._audit_sync_state()
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                _sync_report_text(audit),
                reply_markup=_sync_report_markup(audit),
            )
            self._telegram.answer_callback_query(callback_query_id)
            return

        self._telegram.answer_callback_query(callback_query_id, "Unknown response action.")

    def _show_project_picker(self, topic_project: TopicProject) -> None:
        if topic_project.picker_message_id is None:
            raise ValueError("picker_message_id is required to show the project picker.")
        self._telegram.edit_message_text(
            topic_project.chat_id,
            topic_project.picker_message_id,
            _project_picker_text(
                topic_project.topic_name,
                topic_project.pending_text or "",
                topic_project.pending_local_image_paths,
            ),
            reply_markup=_project_picker_markup(self._state.list_projects()),
        )
        self._state.upsert_topic_project(topic_project)

    def _show_folder_browser(self, topic_project: TopicProject) -> None:
        if topic_project.picker_message_id is None:
            raise ValueError("picker_message_id is required to show the folder browser.")
        browse_path = Path(topic_project.browse_path or str(_browser_home_path())).expanduser()
        browse_page = max(topic_project.browse_page, 0)
        self._telegram.edit_message_text(
            topic_project.chat_id,
            topic_project.picker_message_id,
            _directory_browser_text(browse_path, _browser_home_path()),
            reply_markup=_directory_browser_markup(browse_path, browse_page, _browser_home_path()),
        )
        self._state.upsert_topic_project(
            TopicProject(
                chat_id=topic_project.chat_id,
                message_thread_id=topic_project.message_thread_id,
                topic_name=topic_project.topic_name,
                project_id=topic_project.project_id,
                picker_message_id=topic_project.picker_message_id,
                pending_update_id=topic_project.pending_update_id,
                pending_user_id=topic_project.pending_user_id,
                pending_text=topic_project.pending_text,
                pending_local_image_paths=topic_project.pending_local_image_paths,
                browse_path=str(browse_path),
                browse_page=browse_page,
            )
        )

    def _bind_topic_project(self, topic_project: TopicProject) -> None:
        if not topic_project.project_id:
            raise ValueError("project_id is required to bind a topic.")
        existing_binding = self._binding_by_topic(
            topic_project.chat_id,
            topic_project.message_thread_id,
        )
        binding = self._service.bind_topic_to_project(
            chat_id=topic_project.chat_id,
            message_thread_id=topic_project.message_thread_id,
            project_id=topic_project.project_id,
            thread_title=DEFAULT_NEW_THREAD_TITLE,
        )
        if existing_binding is not None:
            self._state.delete_pending_turn(existing_binding.codex_thread_id)
            self._clear_typing_state(existing_binding.chat_id, existing_binding.message_thread_id)
        self._state.delete_restore_view(topic_project.chat_id, topic_project.message_thread_id)
        if topic_project.picker_message_id is not None:
            self._telegram.edit_message_reply_markup(
                topic_project.chat_id,
                topic_project.picker_message_id,
                None,
            )
        if (
            topic_project.pending_update_id is not None
            and topic_project.pending_user_id is not None
            and topic_project.pending_text is not None
        ):
            self._enqueue_bound_inbound(
                binding,
                telegram_update_id=topic_project.pending_update_id,
                from_user_id=topic_project.pending_user_id,
                text=topic_project.pending_text,
                local_image_paths=topic_project.pending_local_image_paths,
            )
        self._state.delete_topic_project(topic_project.chat_id, topic_project.message_thread_id)
        self._telegram.send_message(
            topic_project.chat_id,
            topic_project.message_thread_id,
            f"Bound this topic to {Path(topic_project.project_id).name} and created thread '{DEFAULT_NEW_THREAD_TITLE}'.",
        )

    def _open_project_picker(
        self,
        *,
        chat_id: int,
        message_thread_id: int,
        topic_name: str | None,
        pending_update_id: int | None = None,
        pending_user_id: int | None = None,
        pending_text: str | None = None,
        pending_local_image_paths: tuple[str, ...] = (),
    ) -> None:
        existing = self._state.get_topic_project(chat_id, message_thread_id)
        if existing is not None and existing.picker_message_id is not None:
            self._show_project_picker(
                TopicProject(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    topic_name=topic_name or existing.topic_name,
                    project_id=None,
                    picker_message_id=existing.picker_message_id,
                    pending_update_id=pending_update_id,
                    pending_user_id=pending_user_id,
                    pending_text=pending_text,
                    pending_local_image_paths=pending_local_image_paths,
                    browse_path=None,
                    browse_page=0,
                )
            )
            return

        picker_message_id = self._telegram.send_message(
            chat_id,
            message_thread_id,
            _project_picker_text(topic_name, pending_text or "", pending_local_image_paths),
            reply_markup=_project_picker_markup(self._state.list_projects()),
        )
        self._state.upsert_topic_project(
            TopicProject(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                topic_name=topic_name,
                project_id=None,
                picker_message_id=picker_message_id,
                pending_update_id=pending_update_id,
                pending_user_id=pending_user_id,
                pending_text=pending_text,
                pending_local_image_paths=pending_local_image_paths,
                browse_path=None,
                browse_page=0,
            )
        )

    def _handle_command(
        self,
        update: dict[str, object],
        *,
        command_name: str,
        command_args: str,
    ) -> None:
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        binding = self._binding_by_topic(chat_id, message_thread_id)

        if command_name == "help":
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                _commands_text(),
            )
            return

        if command_name == "doctor":
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                self._doctor_text(chat_id, message_thread_id),
            )
            return

        if command_name == "projects":
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                self._projects_text(),
            )
            return

        if command_name == "threads":
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                self._threads_text(),
            )
            return

        if command_name == "status":
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                self._status_text(binding, chat_id, message_thread_id),
            )
            return

        if command_name == "history":
            if binding is None:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    "No Codex thread is bound to this topic yet.",
                )
                return
            self._show_history_message(binding)
            return

        if command_name == "resume":
            if binding is None:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    "No Codex thread is bound to this topic yet.",
                )
                return
            if not self._is_primary_binding(binding):
                self._telegram.send_message(chat_id, message_thread_id, _mirror_control_text())
                return
            self._open_resume_picker(binding)
            return

        if command_name == "restore":
            if binding is None:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    "This topic is not bound to any Codex thread.",
                )
                return
            if not self._is_primary_binding(binding):
                self._telegram.send_message(chat_id, message_thread_id, _mirror_control_text())
                return
            if not self._offer_restore_prompt(binding):
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    "Nothing to restore. This topic is already healthy.",
                )
            return

        if command_name == "unbind":
            if binding is None:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    "This topic is not bound to any Codex thread.",
                )
                return
            if not self._is_primary_binding(binding):
                self._telegram.send_message(chat_id, message_thread_id, _mirror_control_text())
                return
            mirror_count = self._unbind_topic(binding)
            thread = self._codex.read_thread(binding.codex_thread_id)
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                _unbind_message_text(
                    thread_title=thread.title,
                    codex_thread_id=binding.codex_thread_id,
                    mirror_count=mirror_count,
                ),
            )
            return

        if command_name == "bindings":
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                self._bindings_dashboard_text(),
                reply_markup=_sessions_dashboard_markup(),
            )
            return

        if command_name == "sync":
            audit = self._audit_sync_state()
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                _sync_report_text(audit),
                reply_markup=_sync_report_markup(audit),
            )
            return

        if command_name == "create_thread":
            if binding is not None and not self._is_primary_binding(binding):
                self._telegram.send_message(chat_id, message_thread_id, _mirror_control_text())
                return
            if not self._start_new_thread(
                chat_id,
                message_thread_id,
                binding,
                thread_title=command_args or DEFAULT_NEW_THREAD_TITLE,
            ):
                self._open_project_picker(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    topic_name=self._topic_name_for_command(chat_id, message_thread_id),
                )
            return

        if command_name == "project":
            if binding is not None and not self._is_primary_binding(binding):
                self._telegram.send_message(chat_id, message_thread_id, _mirror_control_text())
                return
            self._open_project_picker(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                topic_name=self._topic_name_for_command(chat_id, message_thread_id),
            )
            return

    def _show_history_message(
        self,
        binding: Binding,
        *,
        page_index: int = -1,
        message_id: int | None = None,
    ) -> None:
        thread = self._codex.read_thread(binding.codex_thread_id)
        rendered_page = render_history_page(
            display_name=binding.topic_name or self._history_display_name(binding, thread),
            thread_id=binding.codex_thread_id,
            entries=self._codex.list_history_entries(binding.codex_thread_id),
            page_index=page_index,
        )
        if message_id is None:
            message_id = self._telegram.send_message(
                binding.chat_id,
                binding.message_thread_id,
                rendered_page.text,
                reply_markup=rendered_page.reply_markup,
            )
        else:
            self._telegram.edit_message_text(
                binding.chat_id,
                message_id,
                rendered_page.text,
                reply_markup=rendered_page.reply_markup,
            )
        self._state.upsert_history_view(
            HistoryViewState(
                chat_id=binding.chat_id,
                message_thread_id=binding.message_thread_id,
                message_id=message_id,
                codex_thread_id=binding.codex_thread_id,
                page_index=rendered_page.page_index,
            )
        )

    @staticmethod
    def _history_display_name(binding: Binding, thread: CodexThread) -> str:
        return binding.topic_name or format_topic_name(binding.project_id or thread.cwd, thread.title)

    def _open_resume_picker(self, binding: Binding, *, page_index: int = 0, message_id: int | None = None) -> None:
        project_id = binding.project_id or self._codex.read_thread(binding.codex_thread_id).cwd
        if not project_id:
            self._telegram.send_message(
                binding.chat_id,
                binding.message_thread_id,
                "This topic is bound, but the Codex project path is missing.",
            )
            return
        threads = self._codex.list_resumable_threads(
            project_id,
            exclude_thread_id=binding.codex_thread_id,
        )
        if not threads:
            if message_id is None:
                self._telegram.send_message(
                    binding.chat_id,
                    binding.message_thread_id,
                    "No other Codex threads were found in this project.",
                )
            else:
                self._telegram.edit_message_text(
                    binding.chat_id,
                    message_id,
                    "No other Codex threads were found in this project.",
                    reply_markup=None,
                )
            self._state.delete_resume_view(binding.chat_id, binding.message_thread_id)
            return
        text, reply_markup = render_resume_picker(
            project_id=project_id,
            threads=threads,
            page_index=page_index,
        )
        if message_id is None:
            message_id = self._telegram.send_message(
                binding.chat_id,
                binding.message_thread_id,
                text,
                reply_markup=reply_markup,
            )
        else:
            self._telegram.edit_message_text(
                binding.chat_id,
                message_id,
                text,
                reply_markup=reply_markup,
            )
        self._state.upsert_resume_view(
            ResumeViewState(
                chat_id=binding.chat_id,
                message_thread_id=binding.message_thread_id,
                message_id=message_id,
                project_id=project_id,
                page_index=page_index,
            )
        )

    def _offer_restore_prompt(
        self,
        binding: Binding,
        *,
        message_id: int | None = None,
    ) -> bool:
        issue_kind = self._restore_issue_for_binding(binding)
        if issue_kind is None:
            self._state.delete_restore_view(binding.chat_id, binding.message_thread_id)
            return False
        prompt = render_restore_prompt(
            issue_kind=issue_kind,
            topic_name=strip_topic_status_prefix(binding.topic_name or "") or binding.codex_thread_id,
            thread_id=binding.codex_thread_id,
        )
        existing_restore_view = self._state.get_restore_view(binding.chat_id, binding.message_thread_id)
        if message_id is None and existing_restore_view is not None:
            message_id = existing_restore_view.message_id
        if message_id is None:
            message_id = self._telegram.send_message(
                binding.chat_id,
                binding.message_thread_id,
                prompt.text,
                reply_markup=prompt.reply_markup,
            )
        else:
            self._telegram.edit_message_text(
                binding.chat_id,
                message_id,
                prompt.text,
                reply_markup=prompt.reply_markup,
            )
        self._state.upsert_restore_view(
            RestoreViewState(
                chat_id=binding.chat_id,
                message_thread_id=binding.message_thread_id,
                message_id=message_id,
                codex_thread_id=binding.codex_thread_id,
                issue_kind=issue_kind,
            )
        )
        return True

    @staticmethod
    def _restore_issue_for_binding(binding: Binding) -> str | None:
        if binding.binding_status == CLOSED_BINDING_STATUS:
            return RESTORE_ISSUE_CLOSED
        if binding.binding_status == DELETED_BINDING_STATUS:
            return RESTORE_ISSUE_DELETED
        return None

    def _start_new_thread(
        self,
        chat_id: int,
        message_thread_id: int,
        binding: Binding | None,
        *,
        thread_title: str,
    ) -> bool:
        if binding is None:
            return False
        project_id = binding.project_id or self._codex.read_thread(binding.codex_thread_id).cwd
        if not project_id:
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                "This topic is bound, but the Codex project path is missing.",
            )
            return True
        previous_thread_id = binding.codex_thread_id
        new_binding = self._service.bind_topic_to_project(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            project_id=project_id,
            thread_title=thread_title,
        )
        self._state.delete_pending_turn(previous_thread_id)
        self._state.delete_restore_view(chat_id, message_thread_id)
        self._clear_typing_state(chat_id, message_thread_id)
        self._telegram.send_message(
            chat_id,
            message_thread_id,
            (
                f"Started a new Codex thread in {Path(project_id).name}.\n"
                f"Thread id: `{new_binding.codex_thread_id}`"
            ),
        )
        return True

    def _unbind_topic(self, binding: Binding) -> int:
        mirror_bindings = self._state.list_mirror_bindings_for_thread(binding.codex_thread_id)
        for target in [binding, *mirror_bindings]:
            unbound_topic_name = self._unbound_topic_name(target)
            try:
                if unbound_topic_name:
                    self._telegram.edit_forum_topic(
                        target.chat_id,
                        target.message_thread_id,
                        unbound_topic_name,
                    )
            except Exception as exc:
                if not (
                    is_missing_topic_error(exc)
                    or is_topic_edit_permission_error(exc)
                ):
                    raise
            self._state.upsert_topic_project(
                TopicProject(
                    chat_id=target.chat_id,
                    message_thread_id=target.message_thread_id,
                    topic_name=unbound_topic_name,
                    project_id=None,
                    picker_message_id=None,
                )
            )
            self._state.set_topic_project_last_seen(
                target.chat_id,
                target.message_thread_id,
                time.time(),
            )
            self._state.delete_history_view(target.chat_id, target.message_thread_id)
            self._state.delete_resume_view(target.chat_id, target.message_thread_id)
            self._state.delete_restore_view(target.chat_id, target.message_thread_id)
            self._state.delete_topic_history(target.chat_id, target.message_thread_id)
            self._clear_typing_state(target.chat_id, target.message_thread_id)
            self._clear_topic_status_override(target.chat_id, target.message_thread_id)

        self._state.delete_pending_turn(binding.codex_thread_id)
        self._state.delete_pending_inbound_for_thread(binding.codex_thread_id)
        self._state.delete_topic_lifecycle(binding.codex_thread_id)
        self._state.delete_outbound_messages(binding.codex_thread_id)
        for mirror_binding in mirror_bindings:
            self._state.delete_mirror_outbound_messages(
                binding.codex_thread_id,
                chat_id=mirror_binding.chat_id,
            )
            self._state.delete_mirror_binding(
                binding.codex_thread_id,
                chat_id=mirror_binding.chat_id,
            )
        for topic_creation_job in self._state.list_topic_creation_jobs():
            if topic_creation_job.codex_thread_id != binding.codex_thread_id:
                continue
            self._state.delete_topic_creation_job(
                topic_creation_job.codex_thread_id,
                topic_creation_job.chat_id,
            )
        self._state.delete_binding(binding.codex_thread_id)
        return len(mirror_bindings)

    def _unbound_topic_name(self, binding: Binding) -> str | None:
        topic_name = strip_topic_status_prefix(binding.topic_name or "").strip()
        if topic_name:
            return topic_name
        thread = self._codex.read_thread(binding.codex_thread_id)
        fallback_name = format_topic_name(binding.project_id or thread.cwd, thread.title).strip()
        return fallback_name or None

    def _topic_name_for_command(self, chat_id: int, message_thread_id: int) -> str | None:
        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is not None:
            return binding.topic_name
        topic_project = self._state.get_topic_project(chat_id, message_thread_id)
        if topic_project is not None:
            return topic_project.topic_name
        return None

    def _enqueue_bound_inbound(
        self,
        binding: Binding,
        *,
        telegram_update_id: int,
        from_user_id: int,
        text: str = "",
        local_image_paths: tuple[str, ...] = (),
    ) -> None:
        pending_turn = self._state.get_pending_turn(binding.codex_thread_id)
        self._state.enqueue_inbound(
            InboundMessage(
                telegram_update_id=telegram_update_id,
                chat_id=binding.chat_id,
                message_thread_id=binding.message_thread_id,
                from_user_id=from_user_id,
                codex_thread_id=binding.codex_thread_id,
                text=text,
                local_image_paths=local_image_paths,
            )
        )
        self._state.record_topic_history(
            binding.chat_id,
            binding.message_thread_id,
            text=text,
            local_image_paths=local_image_paths,
        )
        self._touch_topic_lifecycle(
            binding.codex_thread_id,
            last_inbound_at=time.time(),
            completed_at=None,
        )
        if pending_turn is None:
            return
        self._telegram.send_message(
            binding.chat_id,
            binding.message_thread_id,
            _queued_message_text(text=text, local_image_paths=local_image_paths),
            reply_markup=_queued_message_markup(telegram_update_id),
        )

    def _queued_inbound_message(
        self,
        telegram_update_id: int,
        codex_thread_id: str,
    ) -> InboundMessage | None:
        for inbound_message in self._state.list_pending_inbound():
            if inbound_message.telegram_update_id != telegram_update_id:
                continue
            if inbound_message.codex_thread_id != codex_thread_id:
                continue
            return inbound_message
        return None

    def _status_text(
        self,
        binding,
        chat_id: int,
        message_thread_id: int,
        *,
        prefix: str = "",
    ) -> str:
        if binding is None:
            return (
                f"{prefix}Topic status\n\n"
                f"Topic id: `{message_thread_id}`\n"
                "Binding: unbound\n"
                "Use `/gateway project` to choose a project or `/gateway create_thread` to open the picker."
            )
        thread = self._codex.read_thread(binding.codex_thread_id)
        pending_turn = self._state.get_pending_turn(binding.codex_thread_id)
        project_name = Path(binding.project_id or thread.cwd or "").name or "-"
        pending_suffix = ""
        if pending_turn is not None:
            pending_suffix = " (waiting for approval)" if pending_turn.waiting_for_approval else " (running)"
        return (
            f"{prefix}Topic status\n\n"
            f"Project: `{project_name}`\n"
            f"Thread title: `{thread.title}`\n"
            f"Thread id: `{binding.codex_thread_id}`\n"
            f"Topic id: `{binding.message_thread_id}`\n"
            f"Codex status: `{thread.status}`{pending_suffix}"
        )

    def _doctor_text(self, chat_id: int, message_thread_id: int) -> str:
        chat = self._telegram.get_chat(self._config.telegram_default_chat_id)
        current_binding = self._binding_by_topic(chat_id, message_thread_id)
        loaded_projects = self._codex.list_loaded_projects()
        loaded_threads = self._codex.list_loaded_threads()
        binding_line = (
            f"Current topic binding: `{current_binding.codex_thread_id}`"
            if current_binding is not None
            else "Current topic binding: unbound"
        )
        return (
            "Gateway doctor\n\n"
            f"Chat: `{chat.get('title') or self._config.telegram_default_chat_id}`"
            f" ({chat.get('type') or 'unknown'})\n"
            f"Loaded projects: `{len(loaded_projects)}`\n"
            f"Loaded threads: `{len(loaded_threads)}`\n"
            f"{binding_line}"
        )

    def _projects_text(self) -> str:
        projects = self._state.list_projects()
        if not projects:
            return "Loaded Codex App projects\n\nNo loaded projects."
        lines = ["Loaded Codex App projects", ""]
        for project in projects:
            lines.append(f"- `{project.project_name}`\n  `{project.project_id}`")
        return "\n".join(lines)

    def _threads_text(self) -> str:
        threads = self._codex.list_loaded_threads()
        if not threads:
            return "Loaded Codex App threads\n\nNo loaded threads."
        lines = ["Loaded Codex App threads", ""]
        for thread in sorted(threads, key=lambda item: (item.cwd, item.title, item.thread_id)):
            project_name = Path(thread.cwd).name or "-"
            lines.append(
                f"- `({project_name}) {thread.title}`\n"
                f"  status `{thread.status}` • id `{thread.thread_id}`"
            )
        return "\n".join(lines)

    def _audit_sync_state(self) -> "_SyncAudit":
        loaded_threads = {thread.thread_id: thread for thread in self._codex.list_loaded_threads()}
        bindings = self._state.list_bindings()
        bound_thread_ids = {binding.codex_thread_id for binding in bindings}
        unbound_loaded_threads = [
            thread
            for thread_id, thread in sorted(loaded_threads.items())
            if thread_id not in bound_thread_ids
        ]

        dead_topics: list[Binding] = []
        unloaded_bindings: list[Binding] = []
        for binding in bindings:
            if binding.codex_thread_id not in loaded_threads:
                unloaded_bindings.append(binding)
            if binding.binding_status == CLOSED_BINDING_STATUS:
                continue
            if binding.binding_status == DELETED_BINDING_STATUS:
                dead_topics.append(binding)
                continue
            try:
                topic_exists = self._telegram.probe_topic(binding.chat_id, binding.message_thread_id)
            except Exception:
                topic_exists = True
            if not topic_exists:
                deleted_binding = self._state.create_binding(
                    replace(
                        binding,
                        binding_status=DELETED_BINDING_STATUS,
                    )
                )
                dead_topics.append(deleted_binding)

        return _SyncAudit(
            loaded_threads=list(loaded_threads.values()),
            bindings=bindings,
            unbound_loaded_threads=unbound_loaded_threads,
            dead_topics=dead_topics,
            unloaded_bindings=unloaded_bindings,
        )

    def _bindings_dashboard_text(self) -> str:
        bindings = self._state.list_bindings()
        if not bindings:
            return (
                "Gateway bindings\n\n"
                "No bound topics yet.\n"
                "Open a Telegram topic and send a message, or use `/gateway create_thread` inside a bound topic."
            )

        loaded_threads = {thread.thread_id: thread for thread in self._codex.list_loaded_threads()}
        mirror_bindings_by_thread: dict[str, list[Binding]] = {}
        for mirror_binding in self._state.list_mirror_bindings():
            mirror_bindings_by_thread.setdefault(mirror_binding.codex_thread_id, []).append(mirror_binding)
        lines = ["Gateway bindings", ""]
        for binding in sorted(bindings, key=lambda item: ((item.topic_name or ""), item.codex_thread_id)):
            thread = loaded_threads.get(binding.codex_thread_id)
            if binding.binding_status == CLOSED_BINDING_STATUS:
                loaded_marker = "🟡"
            elif binding.binding_status == DELETED_BINDING_STATUS:
                loaded_marker = "🔴"
            else:
                loaded_marker = "🟢" if thread is not None else "⚫"
            project_name = Path(binding.project_id or (thread.cwd if thread else "") or "").name or "-"
            thread_title = thread.title if thread is not None else (binding.topic_name or binding.codex_thread_id)
            lines.append(
                f"{loaded_marker} ({project_name}) {thread_title}\n"
                f"topic `{binding.message_thread_id}` • thread `{binding.codex_thread_id}` • status `{binding.binding_status}`"
            )
            mirrors = sorted(
                mirror_bindings_by_thread.get(binding.codex_thread_id, []),
                key=lambda item: (item.chat_id, item.message_thread_id),
            )
            for mirror_binding in mirrors:
                lines.append(
                    f"  ↳ mirror chat `{mirror_binding.chat_id}` topic `{mirror_binding.message_thread_id}`"
                    f" • status `{mirror_binding.binding_status}`"
                )
        pending_jobs = self._state.list_topic_creation_jobs()
        if pending_jobs:
            lines.append("")
            lines.append("Pending mirror topic creation")
            lines.append("")
            for topic_creation_job in pending_jobs:
                lines.append(
                    f"- thread `{topic_creation_job.codex_thread_id}` -> chat `{topic_creation_job.chat_id}`"
                )
        lines.append("")
        lines.append("Use `/gateway sync` to audit bindings and recover deleted topics.")
        return "\n".join(lines)


_CALLBACK_PROJECT_PREFIX = "tp:prj:"
_CALLBACK_BROWSE_OPEN = "tp:browse:open"
_CALLBACK_BROWSE_BACK = "tp:browse:back"
_CALLBACK_BROWSE_HOME = "tp:browse:home"
_CALLBACK_BROWSE_UP = "tp:browse:up"
_CALLBACK_BROWSE_SELECT = "tp:browse:select"
_CALLBACK_BROWSE_PAGE_PREFIX = "tp:browse:page:"
_CALLBACK_BROWSE_ENTER_PREFIX = "tp:browse:enter:"
_CALLBACK_CANCEL = "tp:cancel"
_CALLBACK_NOOP = "tp:noop"
_CALLBACK_SYNC_PREFIX = "gw:sync:"
_CALLBACK_SYNC_FIX = f"{_CALLBACK_SYNC_PREFIX}fix"
_CALLBACK_SYNC_DISMISS = f"{_CALLBACK_SYNC_PREFIX}dismiss"
_CALLBACK_SESSIONS_PREFIX = "gw:sessions:"
_CALLBACK_SESSIONS_REFRESH = f"{_CALLBACK_SESSIONS_PREFIX}refresh"
_CALLBACK_SESSIONS_DISMISS = f"{_CALLBACK_SESSIONS_PREFIX}dismiss"
_CALLBACK_QUEUE_PREFIX = "gw:queue:"
_CALLBACK_QUEUE_STEER_PREFIX = f"{_CALLBACK_QUEUE_PREFIX}steer:"
_CALLBACK_RESPONSE_PREFIX = "gw:resp:"
_CALLBACK_RESPONSE_NOOP = f"{_CALLBACK_RESPONSE_PREFIX}noop"
_CALLBACK_RESPONSE_RECALL_PREFIX = f"{_CALLBACK_RESPONSE_PREFIX}recall:"
_CALLBACK_RESPONSE_NEW = f"{_CALLBACK_RESPONSE_PREFIX}new"
_CALLBACK_RESPONSE_PROJECT = f"{_CALLBACK_RESPONSE_PREFIX}project"
_CALLBACK_RESPONSE_STATUS = f"{_CALLBACK_RESPONSE_PREFIX}status"
_CALLBACK_RESPONSE_SYNC = f"{_CALLBACK_RESPONSE_PREFIX}sync"
_BROWSER_PAGE_SIZE = 6
_COMMAND_RE = re.compile(r"^/([A-Za-z0-9_]+)(?:@[A-Za-z0-9_]+)?(?:\s+(.*))?$")


@dataclass(frozen=True)
class _BotCommand:
    name: str
    description: str
    aliases: tuple[str, ...] = ()


_GATEWAY_SUBCOMMANDS: tuple[_BotCommand, ...] = (
    _BotCommand("doctor", "Show Telegram and Codex App gateway status"),
    _BotCommand("projects", "List loaded Codex App projects"),
    _BotCommand("threads", "List loaded Codex App threads"),
    _BotCommand("history", "Show paginated history for this Codex thread"),
    _BotCommand("resume", "Resume another Codex thread from this project"),
    _BotCommand("restore", "Show recovery options for this topic"),
    _BotCommand("unbind", "Detach this Telegram topic from its Codex thread"),
    _BotCommand("bindings", "List Codex thread to Telegram topic bindings", aliases=("sessions",)),
    _BotCommand("create_thread", "Create a new Codex thread in this topic", aliases=("new", "start")),
    _BotCommand("project", "Choose or switch the Codex project for this topic"),
    _BotCommand("status", "Show the current topic binding and thread status"),
    _BotCommand("sync", "Audit bindings and recover deleted topics"),
    _BotCommand("help", "Show available gateway commands", aliases=("commands",)),
)
BOT_COMMANDS: tuple[tuple[str, str], ...] = (
    ("gateway", "Gateway control commands and status"),
)
_COMMAND_ALIASES: dict[str, str] = {
    alias: command.name
    for command in _GATEWAY_SUBCOMMANDS
    for alias in (command.name, *command.aliases)
}


@dataclass(frozen=True)
class _SyncAudit:
    loaded_threads: list[CodexThread]
    bindings: list[Binding]
    unbound_loaded_threads: list[CodexThread]
    dead_topics: list[Binding]
    unloaded_bindings: list[Binding]

    @property
    def fixable_count(self) -> int:
        return len(self.unbound_loaded_threads) + len(self.dead_topics)


def _sync_report_text(audit: _SyncAudit, *, fixed_count: int = 0) -> str:
    lines: list[str] = []
    if fixed_count > 0:
        lines.append(f"Fixed {fixed_count} issue(s).\n")
    else:
        lines.append("Gateway sync\n")

    lines.append(f"Loaded Codex App threads: {len(audit.loaded_threads)}")
    lines.append(f"Bound Telegram topics: {len(audit.bindings)}")

    if audit.unbound_loaded_threads:
        lines.append(f"⚠ {len(audit.unbound_loaded_threads)} loaded thread(s) have no Telegram topic yet")
    else:
        lines.append("✓ All loaded threads have Telegram topics")

    if audit.dead_topics:
        lines.append(f"⚠ {len(audit.dead_topics)} bound topic(s) were deleted in Telegram")
    else:
        lines.append("✓ All bound Telegram topics are reachable")

    if audit.unloaded_bindings:
        lines.append(
            f"ℹ {len(audit.unloaded_bindings)} binding(s) refer to threads not currently loaded in Codex App"
        )

    if audit.fixable_count == 0:
        lines.append("\nNo fixes needed.")

    return "\n".join(lines)


def _sync_report_markup(audit: _SyncAudit) -> dict[str, object] | None:
    if audit.fixable_count == 0:
        return None
    return {
        "inline_keyboard": [
            [
                {"text": f"🔧 Fix {audit.fixable_count}", "callback_data": _CALLBACK_SYNC_FIX},
                {"text": "Dismiss", "callback_data": _CALLBACK_SYNC_DISMISS},
            ]
        ]
    }


def _sessions_dashboard_markup() -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {"text": "Refresh", "callback_data": _CALLBACK_SESSIONS_REFRESH},
                {"text": "Dismiss", "callback_data": _CALLBACK_SESSIONS_DISMISS},
            ]
        ]
    }


def _project_picker_text(
    topic_name: str | None,
    first_text: str,
    local_image_paths: tuple[str, ...] = (),
) -> str:
    topic_line = f"Topic: {topic_name}\n\n" if topic_name else ""
    return (
        "Select Codex Project\n\n"
        f"{topic_line}"
        "Choose an existing loaded Codex App project below, or browse folders from your Mac home directory.\n\n"
        "First message:\n"
        f"{_first_message_summary(first_text, local_image_paths)}"
    )


def _project_picker_markup(projects: list[CodexProject]) -> dict[str, object]:
    keyboard = [
        [{"text": f"📁 {project.project_name}", "callback_data": f"{_CALLBACK_PROJECT_PREFIX}{index}"}]
        for index, project in enumerate(projects)
    ]
    keyboard.append([{"text": "📂 Browse Home Folder", "callback_data": _CALLBACK_BROWSE_OPEN}])
    keyboard.append([{"text": "Cancel", "callback_data": _CALLBACK_CANCEL}])
    return {"inline_keyboard": keyboard}


def _directory_browser_text(current_path: Path, home_path: Path) -> str:
    return (
        "Select Working Directory\n\n"
        f"Current: {_display_path(current_path, home_path)}\n\n"
        "Tap a folder to enter, or select current directory."
    )


def _directory_browser_markup(current_path: Path, page: int, home_path: Path) -> dict[str, object]:
    directories = _list_subdirectories(current_path)
    total_pages = max(1, (len(directories) + _BROWSER_PAGE_SIZE - 1) // _BROWSER_PAGE_SIZE)
    page = min(max(page, 0), total_pages - 1)
    start = page * _BROWSER_PAGE_SIZE
    page_directories = directories[start : start + _BROWSER_PAGE_SIZE]

    keyboard: list[list[dict[str, str]]] = []
    for row_start in range(0, len(page_directories), 2):
        row: list[dict[str, str]] = []
        for offset, directory in enumerate(page_directories[row_start : row_start + 2]):
            directory_index = start + row_start + offset
            row.append(
                {
                    "text": f"📁 {directory.name}",
                    "callback_data": f"{_CALLBACK_BROWSE_ENTER_PREFIX}{directory_index}",
                }
            )
        keyboard.append(row)

    if total_pages > 1:
        keyboard.append(
            [
                {
                    "text": "◀",
                    "callback_data": f"{_CALLBACK_BROWSE_PAGE_PREFIX}{page - 1}" if page > 0 else _CALLBACK_NOOP,
                },
                {
                    "text": f"{page + 1}/{total_pages}",
                    "callback_data": _CALLBACK_NOOP,
                },
                {
                    "text": "▶",
                    "callback_data": f"{_CALLBACK_BROWSE_PAGE_PREFIX}{page + 1}" if page < total_pages - 1 else _CALLBACK_NOOP,
                },
            ]
        )

    keyboard.append(
        [
            {"text": "..", "callback_data": _CALLBACK_BROWSE_UP},
            {"text": "🏠", "callback_data": _CALLBACK_BROWSE_HOME},
            {"text": "Select", "callback_data": _CALLBACK_BROWSE_SELECT},
        ]
    )
    keyboard.append(
        [
            {"text": "← Projects", "callback_data": _CALLBACK_BROWSE_BACK},
            {"text": "Cancel", "callback_data": _CALLBACK_CANCEL},
        ]
    )
    return {"inline_keyboard": keyboard}


def _browser_home_path() -> Path:
    return Path.home()


def _display_path(current_path: Path, home_path: Path) -> str:
    try:
        relative = current_path.relative_to(home_path)
    except ValueError:
        return str(current_path)
    if str(relative) == ".":
        return "~"
    return f"~/{relative}"


def _list_subdirectories(current_path: Path) -> list[Path]:
    try:
        directories = [
            entry
            for entry in current_path.iterdir()
            if entry.is_dir() and not entry.name.startswith(".")
        ]
    except OSError:
        return []
    return sorted(directories, key=lambda entry: entry.name.lower())


def _normalized_local_image_paths(update: dict[str, object]) -> tuple[str, ...]:
    raw_paths = update.get("local_image_paths")
    if not isinstance(raw_paths, (tuple, list)):
        return ()
    return tuple(str(path) for path in raw_paths if isinstance(path, str))


def _first_message_summary(first_text: str, local_image_paths: tuple[str, ...]) -> str:
    parts: list[str] = []
    if first_text:
        parts.append(first_text)
    if local_image_paths:
        image_count = len(local_image_paths)
        label = "image" if image_count == 1 else "images"
        parts.append(f"[{image_count} {label} attached]")
    if not parts:
        return "(empty message)"
    return "\n".join(parts)


def _turn_status_text(terminal_status: str) -> str:
    if terminal_status == "interrupted":
        return "Codex started processing your message, but the turn was interrupted before a final answer was produced."
    if terminal_status == "failed":
        return "Codex started processing your message, but the turn failed before a final answer was produced."
    return f"Codex turn ended with status `{terminal_status}` before a final answer was produced."


def _mirror_control_text() -> str:
    return "Mirror topics can chat with Codex, but project and thread controls stay in the primary topic."


def _unbind_message_text(
    *,
    thread_title: str,
    codex_thread_id: str,
    mirror_count: int,
) -> str:
    lines = [
        "✂ Unbound this topic from Codex thread.",
        "",
        f"Thread title: `{thread_title}`",
        f"Thread id: `{codex_thread_id}`",
    ]
    if mirror_count > 0:
        lines.append(
            f"Detached `{mirror_count}` mirror topic(s) for the same Codex thread."
        )
    lines.append("The Codex thread is still available in Codex App.")
    lines.append(
        "Send a message in this topic to choose a project and create or bind a new thread."
    )
    return "\n".join(lines)


def _is_terminal_turn_status(status: str) -> bool:
    return status in {"completed", "failed", "interrupted"}


def _split_outbound_text(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        parts.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return [part for part in parts if part]


def _parse_command(text: str) -> tuple[str, str] | None:
    match = _COMMAND_RE.match(text.strip())
    if match is None:
        return None
    command_name = match.group(1).lower()
    command_args = (match.group(2) or "").strip()
    if command_name != "gateway":
        return None
    if not command_args:
        return ("help", "")

    subcommand_name, _, remainder = command_args.partition(" ")
    canonical_name = _COMMAND_ALIASES.get(subcommand_name.lower())
    if canonical_name is None:
        return ("help", "")
    return canonical_name, remainder.strip()


def _parse_topic_name(topic_name: str) -> tuple[str, str] | None:
    match = re.match(r"^\((?P<project>[^)]+)\)\s+(?P<title>.+)$", topic_name.strip())
    if match is None:
        return None
    return match.group("project").strip(), match.group("title").strip()


def _commands_text() -> str:
    lines = ["Available gateway commands:"]
    lines.append("/gateway <subcommand> - Run a gateway control action")
    lines.append("")
    lines.append("Gateway subcommands:")
    for command in _GATEWAY_SUBCOMMANDS:
        lines.append(f"/gateway {command.name} - {command.description}")
    lines.append("")
    lines.append("Compatibility aliases inside `/gateway`: new, start, sessions, commands")
    lines.append("All other slash commands are passed through to the bound Codex thread unchanged.")
    return "\n".join(lines)


def _queued_message_markup(telegram_update_id: int) -> dict[str, object]:
    return {
        "inline_keyboard": [
            [{"text": "Steer", "callback_data": f"{_CALLBACK_QUEUE_STEER_PREFIX}{telegram_update_id}"}]
        ]
    }


def _queued_message_text(
    *,
    text: str,
    local_image_paths: tuple[str, ...],
) -> str:
    lines = [
        "Queued while Codex is still answering. This will run after the current answer finishes.",
        "",
        "Queued message:",
        _queued_message_preview(text=text, local_image_paths=local_image_paths),
    ]
    return "\n".join(lines)


def _queued_message_preview(
    *,
    text: str,
    local_image_paths: tuple[str, ...],
    text_limit: int = 1000,
) -> str:
    parts: list[str] = []
    normalized_text = " ".join(text.split())
    if normalized_text:
        if len(normalized_text) > text_limit:
            normalized_text = normalized_text[: text_limit - 1].rstrip() + "…"
        parts.append(normalized_text)
    if local_image_paths:
        image_count = len(local_image_paths)
        label = "image" if image_count == 1 else "images"
        parts.append(f"[{image_count} {label}]")
    return "\n".join(parts) or "(empty message)"


def _steer_callback_text(error: Exception) -> str:
    normalized_error = str(error).lower()
    if "no active turn to steer" in normalized_error:
        return "Codex is no longer answering. This message stays queued."
    if "active_turn_not_steerable" in normalized_error or "cannot steer" in normalized_error:
        return "This Codex turn cannot be steered. The message stays queued."
    return "Steer failed. The message stays queued."


def _is_terminal_steer_error(error: Exception) -> bool:
    normalized_error = str(error).lower()
    return (
        "no active turn to steer" in normalized_error
        or "active_turn_not_steerable" in normalized_error
        or "cannot steer" in normalized_error
    )


def _response_widget_markup(
    *,
    status: str,
    history: list[TopicHistoryEntry],
) -> dict[str, object]:
    rows: list[list[dict[str, str]]] = [
        [{"text": _response_status_label(status), "callback_data": _CALLBACK_RESPONSE_NOOP}]
    ]
    if status == "ready" and history:
        rows.append(
            [
                {
                    "text": f"↑ {_history_entry_label(entry)}",
                    "callback_data": f"{_CALLBACK_RESPONSE_RECALL_PREFIX}{index}",
                }
                for index, entry in enumerate(history[:2])
            ]
        )
    if status == "ready":
        rows.append(
            [
                {"text": "↺ New", "callback_data": _CALLBACK_RESPONSE_NEW},
                {"text": "📁 Project", "callback_data": _CALLBACK_RESPONSE_PROJECT},
                {"text": "📍 Status", "callback_data": _CALLBACK_RESPONSE_STATUS},
                {"text": "🔄 Sync", "callback_data": _CALLBACK_RESPONSE_SYNC},
            ]
        )
    return {"inline_keyboard": rows}


def _response_status_label(status: str) -> str:
    if status == "running":
        return "⏳ Working"
    if status == "approval":
        return "⚠ Waiting For Approval"
    if status == "failed":
        return "⚠ Turn Failed"
    if status == "interrupted":
        return "⚠ Turn Interrupted"
    return "✓ Ready"


def _history_entry_label(entry: TopicHistoryEntry, limit: int = 20) -> str:
    parts: list[str] = []
    if entry.text:
        parts.append(" ".join(entry.text.split()))
    if entry.local_image_paths:
        image_count = len(entry.local_image_paths)
        label = "image" if image_count == 1 else "images"
        parts.append(f"[{image_count} {label}]")
    label = " ".join(parts) or "(empty message)"
    if len(label) <= limit:
        return label
    return label[: limit - 1].rstrip() + "…"


def _event_turn_id(event_id: str) -> str | None:
    parts = event_id.split(":", 2)
    if len(parts) < 3:
        return None
    return parts[1]
