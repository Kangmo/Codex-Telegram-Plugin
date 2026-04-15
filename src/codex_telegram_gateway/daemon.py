import time
from dataclasses import dataclass, replace
from pathlib import Path
import re

from codex_telegram_gateway.commands_catalog import build_bot_commands, register_bot_commands_if_changed
from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.history_command import (
    CALLBACK_HISTORY_PREFIX,
    parse_history_callback,
    render_history_page,
)
from codex_telegram_gateway.interactive_bridge import (
    InteractivePromptSession,
    apply_interactive_callback,
    apply_interactive_text_answer,
    parse_interactive_callback,
    render_interactive_prompt,
    start_interactive_prompt_session,
)
from codex_telegram_gateway.inline_query import build_inline_query_results
from codex_telegram_gateway.live_view import (
    CALLBACK_LIVE_VIEW_PREFIX,
    LiveViewState,
    build_live_view_markup,
    capture_hash_for_path,
    parse_live_view_callback,
    render_live_view_caption,
)
from codex_telegram_gateway.mailbox_commands import (
    MailboxPeer,
    parse_mailbox_command,
    render_mailbox_delivery_text,
    render_mailbox_help,
    render_mailbox_peers,
    render_mailbox_recipient_notice,
    render_mailbox_send_ack,
)
from codex_telegram_gateway.remote_actions import (
    CALLBACK_REMOTE_ACTION_PREFIX,
    RemoteActionContext,
    RemotePromptOption,
    build_remote_action_rows,
    parse_remote_action_callback,
)
from codex_telegram_gateway.shell_mode import (
    CALLBACK_SHELL_PREFIX,
    ShellCommandSuggester,
    ShellRunner,
    ShellSuggestionView,
    build_shell_command_suggester,
    build_shell_runner,
    parse_shell_callback,
    parse_shell_request,
    render_shell_help,
    render_shell_result,
    render_shell_suggestion,
)
from codex_telegram_gateway.status_bubble import StatusBubbleSnapshot, build_status_bubble
from codex_telegram_gateway.voice_ingest import (
    TranscriptionProvider,
    build_transcription_provider,
    parse_voice_callback,
    render_voice_prompt,
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
from codex_telegram_gateway.notification_modes import (
    build_verbose_picker,
    normalize_notification_mode,
    notification_mode_button_text,
    parse_verbose_callback,
    should_emit_notification,
)
from codex_telegram_gateway.panes_compat import (
    project_threads_for_panes,
    render_panes_compatibility,
)
from codex_telegram_gateway.ports import CodexBridge, GatewayState, TelegramClient
from codex_telegram_gateway.recall_command import (
    history_entry_label,
    parse_recall_callback,
    render_recall_prompt,
)
from codex_telegram_gateway.screenshot_capture import (
    build_screenshot_provider,
    ScreenshotCaptureError,
    ScreenshotProvider,
)
from codex_telegram_gateway.service import (
    DEFAULT_NEW_THREAD_TITLE,
    GatewayService,
    format_topic_name,
)
from codex_telegram_gateway.sessions_dashboard import (
    SessionsDashboardEntry,
    build_sessions_dashboard,
    parse_sessions_callback,
    render_unbind_confirmation,
)
from codex_telegram_gateway.resume_command import (
    CALLBACK_RESUME_CANCEL,
    CALLBACK_RESUME_PAGE_PREFIX,
    CALLBACK_RESUME_PICK_PREFIX,
    parse_resume_page_callback,
    parse_resume_pick_callback,
    render_resume_picker,
)
from codex_telegram_gateway.send_callbacks import parse_send_callback
from codex_telegram_gateway.send_command import (
    build_send_browser_page,
    build_send_preview_page,
)
from codex_telegram_gateway.send_security import (
    build_send_preview,
    browse_project_files,
    search_project_files,
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
    TelegramApiError,
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
from codex_telegram_gateway.toolbar import (
    build_toolbar_markup,
    load_toolbar_config,
    parse_toolbar_callback,
    render_toolbar_text,
)
from codex_telegram_gateway.upgrade_diagnostics import (
    discover_upgrade_diagnostics,
    render_upgrade_text,
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
        transcriber: TranscriptionProvider | None = None,
        screenshot_provider: ScreenshotProvider | None = None,
        shell_suggester: ShellCommandSuggester | None = None,
        shell_runner: ShellRunner | None = None,
    ) -> None:
        self._config = config
        self._state = state
        self._telegram = telegram
        self._codex = codex
        self._transcriber = transcriber if transcriber is not None else build_transcription_provider(config)
        self._screenshot_provider = (
            screenshot_provider if screenshot_provider is not None else build_screenshot_provider(config)
        )
        self._shell_suggester = (
            shell_suggester if shell_suggester is not None else build_shell_command_suggester(config)
        )
        self._shell_runner = shell_runner if shell_runner is not None else build_shell_runner()
        self._toolbar_config = load_toolbar_config(config.toolbar_config_path)
        self._last_typing_sent_at: dict[tuple[int, int], float] = {}
        self._topic_status_overrides: dict[tuple[int, int], str] = {}
        self._topic_status_disabled_chats: set[int] = set()
        self._interactive_prompt_sessions: dict[str, InteractivePromptSession] = {}
        self._interactive_prompt_renders: dict[str, tuple[str, dict[str, object] | None]] = {}
        self._status_bubble_renders: dict[tuple[int, int], tuple[str, dict[str, object]]] = {}
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
        pending_inbound_counts: dict[str, int] = {}
        for inbound_message in self._state.list_pending_inbound():
            pending_inbound_counts[inbound_message.codex_thread_id] = (
                pending_inbound_counts.get(inbound_message.codex_thread_id, 0) + 1
            )
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
            events = self._codex.list_events(binding.codex_thread_id)
            latest_summary = _latest_visible_summary(events)
            active_targets: list[Binding] = []
            for target in targets:
                if target.binding_status == DELETED_BINDING_STATUS:
                    continue
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
                active_targets.append(target)
                if target.binding_status == ACTIVE_BINDING_STATUS:
                    for event in events:
                        active_turn_id = pending_turn.turn_id if pending_turn is not None else None
                        active_turn_result = turn_result if active_turn_id == _event_turn_id(event.event_id) else None
                        self._sync_outbound_event(target, event, active_turn_result=active_turn_result)

            if pending_turn is None:
                for target in active_targets:
                    if target.binding_status == ACTIVE_BINDING_STATUS:
                        self._sync_status_bubble_for_binding(
                            target,
                            thread=thread,
                            pending_turn=None,
                            turn_result=None,
                            latest_summary=latest_summary,
                            queued_count=pending_inbound_counts.get(binding.codex_thread_id, 0),
                        )
                continue
            if turn_result is None:
                turn_result = self._codex.inspect_turn(binding.codex_thread_id, pending_turn.turn_id)

            self._sync_interactive_prompt_for_binding(binding)
            active_turn_has_completion_summary = any(
                getattr(event, "kind", None) == "completion_summary"
                and _event_turn_id(event.event_id) == pending_turn.turn_id
                for event in events
            )

            if turn_result.waiting_for_approval or not _is_terminal_turn_status(turn_result.status):
                for target in active_targets:
                    if target.binding_status == ACTIVE_BINDING_STATUS:
                        self._send_typing_if_due(target.chat_id, target.message_thread_id)
                        self._sync_status_bubble_for_binding(
                            target,
                            thread=thread,
                            pending_turn=pending_turn,
                            turn_result=turn_result,
                            latest_summary=latest_summary,
                            queued_count=pending_inbound_counts.get(binding.codex_thread_id, 0),
                        )
                    else:
                        self._clear_typing_state(target.chat_id, target.message_thread_id)
                continue

            self._state.delete_pending_turn(binding.codex_thread_id)
            self._clear_interactive_prompt_topic(
                binding.chat_id,
                binding.message_thread_id,
                codex_thread_id=binding.codex_thread_id,
            )
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
                if (
                    target.binding_status == ACTIVE_BINDING_STATUS
                    and turn_result.status != "completed"
                    and not active_turn_has_completion_summary
                ):
                    self._send_binding_notification(
                        target,
                        text=_turn_status_text(turn_result.status),
                        kind="error",
                    )
                if target.binding_status == ACTIVE_BINDING_STATUS:
                    self._sync_status_bubble_for_binding(
                        target,
                        thread=thread,
                        pending_turn=None,
                        turn_result=None,
                        latest_summary=latest_summary,
                        queued_count=pending_inbound_counts.get(binding.codex_thread_id, 0),
                    )
            if turn_result.status == "completed":
                self._mark_topic_completed(binding.codex_thread_id)

    def poll_telegram_once(self) -> None:
        self._sync_projects_once()
        self._tick_live_views()
        offset = self._state.get_telegram_cursor()
        updates = self._telegram.get_updates(offset=offset)
        highest_seen = offset

        for update in updates:
            update_id = int(update["update_id"])
            highest_seen = max(highest_seen, update_id + 1)

            try:
                kind = str(update.get("kind") or "message")
                if kind == "inline_query":
                    from_user_id = int(update["from_user_id"])
                    if from_user_id not in self._config.telegram_allowed_user_ids:
                        continue
                    self._handle_inline_query(update)
                    continue
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
                if kind == "unsupported_message":
                    if from_user_id not in self._config.telegram_allowed_user_ids:
                        continue
                    notice = str(update.get("notice") or "").strip()
                    if notice:
                        self._telegram.send_message(chat_id, message_thread_id, notice)
                    continue
                if kind == "voice_message":
                    if from_user_id not in self._config.telegram_allowed_user_ids:
                        continue
                    self._handle_voice_message(update)
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
                if self._handle_interactive_text_reply(
                    binding=binding,
                    text=text,
                    local_image_paths=local_image_paths,
                ):
                    continue
                self._refresh_command_menu_for_passthrough(text)

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
        self._deliver_mailbox_once()

    def _sync_outbound_event(self, binding, event, *, active_turn_result: TurnResult | None = None) -> None:
        if _is_artifact_event_kind(event.kind):
            self._sync_artifact_event(binding, event)
            return
        if not _is_renderable_event_kind(event.kind):
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

    def _sync_artifact_event(self, binding, event) -> None:
        outbound_message = self._get_outbound_message_for_target(binding, event.event_id)
        if outbound_message is not None or self._has_seen_event_for_target(binding, event.event_id):
            return

        file_path = Path(str(getattr(event, "file_path", "") or "")).expanduser()
        if not file_path.is_file():
            return

        caption = str(getattr(event, "text", "")).strip() or None
        try:
            if event.kind == "artifact_photo":
                message_id = self._telegram.send_photo_file(
                    binding.chat_id,
                    binding.message_thread_id,
                    file_path,
                    caption=caption,
                )
            else:
                message_id = self._telegram.send_document_file(
                    binding.chat_id,
                    binding.message_thread_id,
                    file_path,
                    caption=caption,
                )
        except Exception as exc:
            if self._mark_binding_deleted_if_missing_topic(binding, exc):
                return
            raise

        self._upsert_outbound_message_for_target(
            binding,
            OutboundMessage(
                codex_thread_id=binding.codex_thread_id,
                event_id=event.event_id,
                telegram_message_ids=(message_id,),
                text=caption or "",
                reply_markup=None,
            ),
        )
        self._mark_event_seen_for_target(binding, event.event_id)
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
        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is not None and not self._should_emit_binding_notification(binding, kind="typing"):
            return
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

    def _should_emit_binding_notification(self, binding: Binding, *, kind: str) -> bool:
        return should_emit_notification(binding.sync_mode, kind)

    def _send_binding_notification(self, binding: Binding, *, text: str, kind: str) -> None:
        if not self._should_emit_binding_notification(binding, kind=kind):
            return
        try:
            self._telegram.send_message(
                binding.chat_id,
                binding.message_thread_id,
                text,
            )
        except Exception as exc:
            if not self._mark_binding_deleted_if_missing_topic(binding, exc):
                raise

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

    def _sync_status_bubble_for_binding(
        self,
        binding: Binding,
        *,
        thread: CodexThread,
        pending_turn: PendingTurn | None,
        turn_result: TurnResult | None,
        latest_summary: str | None,
        queued_count: int,
    ) -> None:
        history = self._state.list_topic_history(binding.chat_id, binding.message_thread_id, limit=2)
        snapshot = StatusBubbleSnapshot(
            project_name=Path(binding.project_id or thread.cwd or "").name or "-",
            thread_title=thread.title,
            state=self._status_bubble_state(binding, pending_turn, turn_result),
            queued_count=queued_count,
            latest_summary=latest_summary or "No assistant reply yet.",
            history_labels=tuple(_history_entry_label(entry) for entry in history),
            remote_action_rows=self._status_bubble_remote_action_rows(
                binding=binding,
                pending_turn=pending_turn,
                turn_result=turn_result,
                history=history,
            ),
        )
        text, reply_markup = build_status_bubble(snapshot)
        key = (binding.chat_id, binding.message_thread_id)
        existing_view = self._state.get_status_bubble_view(binding.chat_id, binding.message_thread_id)
        cached_render = self._status_bubble_renders.get(key)
        if (
            existing_view is not None
            and existing_view.codex_thread_id == binding.codex_thread_id
            and cached_render == (text, reply_markup)
        ):
            return

        try:
            if existing_view is not None:
                message_id = existing_view.message_id
                self._telegram.edit_message_text(
                    binding.chat_id,
                    message_id,
                    text,
                    reply_markup=reply_markup,
                )
            else:
                message_id = self._telegram.send_message(
                    binding.chat_id,
                    binding.message_thread_id,
                    text,
                    reply_markup=reply_markup,
                )
        except Exception as exc:
            if self._mark_binding_deleted_if_missing_topic(binding, exc):
                self._state.delete_status_bubble_view(binding.chat_id, binding.message_thread_id)
                self._status_bubble_renders.pop(key, None)
                return
            try:
                message_id = self._telegram.send_message(
                    binding.chat_id,
                    binding.message_thread_id,
                    text,
                    reply_markup=reply_markup,
                )
            except Exception as send_exc:
                if self._mark_binding_deleted_if_missing_topic(binding, send_exc):
                    self._state.delete_status_bubble_view(binding.chat_id, binding.message_thread_id)
                    self._status_bubble_renders.pop(key, None)
                    return
                raise

        self._state.upsert_status_bubble_view(
            StatusBubbleViewState(
                chat_id=binding.chat_id,
                message_thread_id=binding.message_thread_id,
                message_id=message_id,
                codex_thread_id=binding.codex_thread_id,
            )
        )
        self._status_bubble_renders[key] = (text, reply_markup)

    def _status_bubble_state(
        self,
        binding: Binding,
        pending_turn: PendingTurn | None,
        turn_result: TurnResult | None,
    ) -> str:
        topic_status = self._topic_status_for_binding(binding, pending_turn, turn_result)
        if topic_status == TOPIC_STATUS_RUNNING:
            return "running"
        if topic_status == TOPIC_STATUS_APPROVAL:
            return "approval"
        if topic_status == TOPIC_STATUS_FAILED:
            return "failed"
        if topic_status == TOPIC_STATUS_CLOSED:
            return "closed"
        return "ready"

    def _status_bubble_remote_action_rows(
        self,
        *,
        binding: Binding,
        pending_turn: PendingTurn | None,
        turn_result: TurnResult | None,
        history: list[TopicHistoryEntry],
    ) -> tuple[tuple[dict[str, str], ...], ...]:
        state = self._status_bubble_state(binding, pending_turn, turn_result)
        prompt_id: str | None = None
        prompt_options: tuple[RemotePromptOption, ...] = ()
        supports_prompt_choices = False
        if state == "approval":
            for prompt in self._codex.list_pending_prompts(binding.codex_thread_id):
                if prompt.kind not in {"command_approval", "file_change_approval"}:
                    continue
                if not prompt.options:
                    continue
                prompt_id = prompt.prompt_id
                prompt_options = tuple(
                    RemotePromptOption(option_id=option.option_id, label=option.label)
                    for option in prompt.options
                )
                supports_prompt_choices = True
                break
        return build_remote_action_rows(
            RemoteActionContext(
                state=state,
                turn_id=pending_turn.turn_id if pending_turn is not None else None,
                history_count=len(history),
                prompt_id=prompt_id,
                prompt_options=prompt_options,
                supports_interrupt=pending_turn is not None and state == "running",
                supports_continue=(
                    pending_turn is not None
                    and state == "running"
                    and not pending_turn.waiting_for_approval
                ),
                supports_retry=state == "failed",
                supports_prompt_choices=supports_prompt_choices,
            )
        )

    def _sync_interactive_prompt_for_binding(self, binding: Binding) -> None:
        if not self._is_primary_binding(binding):
            return
        prompts = self._codex.list_pending_prompts(binding.codex_thread_id)
        if not prompts:
            return
        prompt = prompts[0]
        session = self._interactive_prompt_sessions.get(prompt.prompt_id)
        if session is None:
            session = start_interactive_prompt_session(prompt)
            self._interactive_prompt_sessions[prompt.prompt_id] = session
        text, reply_markup = render_interactive_prompt(session)
        existing_view = self._state.get_interactive_prompt_view(binding.chat_id, binding.message_thread_id)
        cached_render = self._interactive_prompt_renders.get(prompt.prompt_id)
        if (
            existing_view is not None
            and existing_view.prompt_id == prompt.prompt_id
            and cached_render == (text, reply_markup)
        ):
            return

        try:
            if existing_view is not None and existing_view.prompt_id == prompt.prompt_id:
                message_id = existing_view.message_id
                self._telegram.edit_message_text(
                    binding.chat_id,
                    message_id,
                    text,
                    reply_markup=reply_markup,
                )
            else:
                if existing_view is not None:
                    self._interactive_prompt_sessions.pop(existing_view.prompt_id, None)
                    self._interactive_prompt_renders.pop(existing_view.prompt_id, None)
                message_id = self._telegram.send_message(
                    binding.chat_id,
                    binding.message_thread_id,
                    text,
                    reply_markup=reply_markup,
                )
        except Exception as exc:
            if self._mark_binding_deleted_if_missing_topic(binding, exc):
                return
            raise

        self._interactive_prompt_renders[prompt.prompt_id] = (text, reply_markup)
        self._state.upsert_interactive_prompt_view(
            InteractivePromptViewState(
                chat_id=binding.chat_id,
                message_thread_id=binding.message_thread_id,
                message_id=message_id,
                codex_thread_id=binding.codex_thread_id,
                prompt_id=prompt.prompt_id,
                prompt_kind=prompt.kind,
            )
        )

    def _apply_interactive_prompt_update(
        self,
        binding: Binding,
        *,
        prompt_id: str,
        message_id: int,
        update,
    ) -> None:
        if update.response_payload is not None:
            self._codex.respond_interactive_prompt(prompt_id, update.response_payload)
            self._interactive_prompt_sessions.pop(prompt_id, None)
            self._interactive_prompt_renders.pop(prompt_id, None)
            self._state.delete_interactive_prompt_view(binding.chat_id, binding.message_thread_id)
            self._telegram.edit_message_text(
                binding.chat_id,
                message_id,
                f"Sent your answer to Codex.\n\n{update.session.prompt.title}",
                reply_markup=None,
            )
            return

        text, reply_markup = render_interactive_prompt(update.session)
        self._interactive_prompt_renders[prompt_id] = (text, reply_markup)
        self._telegram.edit_message_text(
            binding.chat_id,
            message_id,
            text,
            reply_markup=reply_markup,
        )

    def _clear_interactive_prompt_topic(
        self,
        chat_id: int,
        message_thread_id: int,
        *,
        codex_thread_id: str | None = None,
    ) -> None:
        prompt_view = self._state.get_interactive_prompt_view(chat_id, message_thread_id)
        if prompt_view is not None:
            try:
                self._telegram.edit_message_reply_markup(chat_id, prompt_view.message_id, None)
            except Exception:
                pass
            self._interactive_prompt_sessions.pop(prompt_view.prompt_id, None)
            self._interactive_prompt_renders.pop(prompt_view.prompt_id, None)
        self._state.delete_interactive_prompt_view(chat_id, message_thread_id)
        if codex_thread_id:
            self._codex.clear_pending_prompts(codex_thread_id)

    def _handle_interactive_text_reply(
        self,
        *,
        binding: Binding,
        text: str,
        local_image_paths: tuple[str, ...],
    ) -> bool:
        prompt_view = self._state.get_interactive_prompt_view(binding.chat_id, binding.message_thread_id)
        if prompt_view is None:
            return False
        session = self._interactive_prompt_sessions.get(prompt_view.prompt_id)
        if session is None:
            return False
        if session.prompt.kind != "tool_request_user_input" or not session.prompt.questions:
            self._telegram.send_message(
                binding.chat_id,
                binding.message_thread_id,
                "Please use the prompt buttons above for this question.",
            )
            return True
        current_question = session.prompt.questions[min(session.question_index, len(session.prompt.questions) - 1)]
        if current_question.is_secret:
            self._telegram.send_message(
                binding.chat_id,
                binding.message_thread_id,
                "This prompt must be answered from Codex App.",
            )
            return True
        if current_question.options and session.awaiting_text_question_id != current_question.question_id:
            self._telegram.send_message(
                binding.chat_id,
                binding.message_thread_id,
                "Please use the prompt buttons above for this question.",
            )
            return True
        if local_image_paths:
            self._telegram.send_message(
                binding.chat_id,
                binding.message_thread_id,
                "This prompt expects a text reply.",
            )
            return True
        try:
            update = apply_interactive_text_answer(session, text)
        except ValueError:
            return False
        self._apply_interactive_prompt_update(
            binding,
            prompt_id=prompt_view.prompt_id,
            message_id=prompt_view.message_id,
            update=update,
        )
        return True

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
        self._state.delete_live_view(binding.chat_id, binding.message_thread_id)
        self._state.delete_voice_prompt_view(binding.chat_id, binding.message_thread_id)
        self._state.delete_shell_view(binding.chat_id, binding.message_thread_id)
        self._state.delete_status_bubble_view(binding.chat_id, binding.message_thread_id)
        self._state.delete_toolbar_view(binding.chat_id, binding.message_thread_id)
        self._status_bubble_renders.pop((binding.chat_id, binding.message_thread_id), None)
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

    def _handle_voice_message(self, update: dict[str, object]) -> None:
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        from_user_id = int(update["from_user_id"])
        file_path = Path(str(update.get("file_path") or "")).expanduser()
        if not file_path.is_file():
            self._telegram.send_message(chat_id, message_thread_id, "Failed to download the voice message.")
            return
        if self._transcriber is None:
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                "Voice transcription is not configured. Set CODEX_TELEGRAM_WHISPER_PROVIDER to enable it.",
            )
            return

        self._telegram.send_chat_action(chat_id, message_thread_id, "typing")
        try:
            result = self._transcriber.transcribe(file_path)
        except Exception as exc:
            self._telegram.send_message(chat_id, message_thread_id, f"Voice transcription failed: {exc}")
            return

        transcript_text = str(getattr(result, "text", "") or "").strip()
        if not transcript_text:
            self._telegram.send_message(chat_id, message_thread_id, "Could not transcribe the voice message.")
            return

        existing_prompt = self._state.get_voice_prompt_view(chat_id, message_thread_id)
        if existing_prompt is not None:
            try:
                self._telegram.edit_message_reply_markup(chat_id, existing_prompt.message_id, None)
            except Exception:
                pass
            self._state.delete_voice_prompt_view(chat_id, message_thread_id)

        prompt_text, reply_markup = render_voice_prompt(transcript_text)
        prompt_message_id = self._telegram.send_message(
            chat_id,
            message_thread_id,
            prompt_text,
            reply_markup=reply_markup,
        )
        binding = self._binding_by_topic(chat_id, message_thread_id)
        self._state.upsert_voice_prompt_view(
            VoicePromptViewState(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                message_id=prompt_message_id,
                codex_thread_id=binding.codex_thread_id if binding is not None else "",
                source_update_id=int(update["update_id"]),
                from_user_id=from_user_id,
                transcript_text=transcript_text,
            )
        )

    def _handle_voice_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        action = parse_voice_callback(str(update["data"]))
        if action is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown voice action.")
            return

        voice_prompt_view = self._state.get_voice_prompt_view(chat_id, message_thread_id)
        if voice_prompt_view is None or voice_prompt_view.message_id != message_id:
            self._telegram.answer_callback_query(callback_query_id, "This voice prompt is stale.")
            return

        if action == "drop":
            self._state.delete_voice_prompt_view(chat_id, message_thread_id)
            self._telegram.edit_message_text(
                chat_id,
                message_id,
                "Voice transcription discarded.",
                reply_markup=None,
            )
            self._telegram.answer_callback_query(callback_query_id, "Discarded.")
            return

        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is not None and binding.binding_status != ACTIVE_BINDING_STATUS:
            if self._is_primary_binding(binding):
                self._offer_restore_prompt(binding)
            self._telegram.answer_callback_query(callback_query_id, "This topic needs restore first.")
            return

        self._state.delete_voice_prompt_view(chat_id, message_thread_id)
        self._telegram.edit_message_text(
            chat_id,
            message_id,
            f"Voice transcription sent.\n\n{voice_prompt_view.transcript_text}",
            reply_markup=None,
        )
        if binding is None:
            topic_project = self._state.get_topic_project(chat_id, message_thread_id)
            self._open_project_picker(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                topic_name=topic_project.topic_name if topic_project else None,
                pending_update_id=voice_prompt_view.source_update_id,
                pending_user_id=voice_prompt_view.from_user_id,
                pending_text=voice_prompt_view.transcript_text,
            )
            self._telegram.answer_callback_query(callback_query_id, "Choose a project.")
            return

        self._enqueue_bound_inbound(
            binding,
            telegram_update_id=voice_prompt_view.source_update_id,
            from_user_id=voice_prompt_view.from_user_id,
            text=voice_prompt_view.transcript_text,
            local_image_paths=(),
        )
        self._telegram.answer_callback_query(callback_query_id, "Queued.")

    def _handle_live_view_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        action = parse_live_view_callback(str(update["data"]))
        if action is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown live view action.")
            return
        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is None:
            self._telegram.answer_callback_query(callback_query_id, "This topic is not bound to any Codex thread.")
            return
        if action == "stop":
            if self._state.get_live_view(chat_id, message_thread_id) is None:
                self._telegram.answer_callback_query(callback_query_id, "Live view is not active.")
                return
            self._stop_live_view(
                chat_id,
                message_thread_id,
                status_suffix="Stopped.",
            )
            self._telegram.answer_callback_query(callback_query_id, "Stopped.")
            return
        try:
            if action == "start":
                self._start_live_view(
                    binding,
                    target_chat_id=chat_id,
                    target_message_thread_id=message_thread_id,
                    existing_message_id=message_id,
                )
                self._telegram.answer_callback_query(callback_query_id, "Live view started.")
                return
            live_view = self._state.get_live_view(chat_id, message_thread_id)
            if live_view is None or live_view.message_id != message_id:
                self._telegram.answer_callback_query(callback_query_id, "Live view is not active.")
                return
            self._refresh_live_view(live_view, force=True)
        except ScreenshotCaptureError as exc:
            self._telegram.answer_callback_query(callback_query_id, f"Live view failed: {exc}")
            return
        self._telegram.answer_callback_query(callback_query_id, "Refreshed.")

    def _handle_inline_query(self, update: dict[str, object]) -> None:
        inline_query_id = str(update["inline_query_id"])
        query = str(update.get("query") or "")
        results = build_inline_query_results(
            query,
            passthrough_commands=self._state.list_passthrough_commands(),
        )
        self._telegram.answer_inline_query(
            inline_query_id,
            results,
            cache_time=0,
            is_personal=True,
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
        if data.startswith(_CALLBACK_VERBOSE_PREFIX):
            self._handle_verbose_callback(update)
            return
        if data.startswith(_CALLBACK_RECALL_PREFIX):
            self._handle_recall_callback(update)
            return
        if data.startswith(_CALLBACK_SEND_PREFIX):
            self._handle_send_callback(update)
            return
        if data.startswith(CALLBACK_LIVE_VIEW_PREFIX):
            self._handle_live_view_callback(update)
            return
        if data.startswith(_CALLBACK_PROMPT_PREFIX):
            self._handle_interactive_prompt_callback(update)
            return
        if data.startswith(_CALLBACK_VOICE_PREFIX):
            self._handle_voice_callback(update)
            return
        if data.startswith(CALLBACK_SHELL_PREFIX):
            self._handle_shell_callback(update)
            return
        if data.startswith(_CALLBACK_TOOLBAR_PREFIX):
            self._handle_toolbar_callback(update)
            return
        if data.startswith(_CALLBACK_QUEUE_PREFIX):
            self._handle_queue_callback(update)
            return
        if data.startswith(CALLBACK_REMOTE_ACTION_PREFIX):
            self._handle_remote_action_callback(update)
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
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        parsed_callback = parse_sessions_callback(str(update["data"]))
        if parsed_callback is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown sessions action.")
            return

        action = str(parsed_callback["action"])
        page_index = int(parsed_callback["page_index"])
        target_chat_id = parsed_callback["chat_id"]
        target_message_thread_id = parsed_callback["message_thread_id"]

        if action == "dismiss":
            self._telegram.edit_message_reply_markup(chat_id, message_id, None)
            self._telegram.answer_callback_query(callback_query_id, "Dismissed.")
            return

        if action == "page":
            self._edit_sessions_dashboard_message(chat_id, message_id, page_index=page_index)
            self._telegram.answer_callback_query(callback_query_id, f"Page {page_index + 1}.")
            return

        if action == "unbind_cancel":
            self._edit_sessions_dashboard_message(chat_id, message_id, page_index=page_index)
            self._telegram.answer_callback_query(callback_query_id, "Cancelled.")
            return

        if action == "refresh" and target_chat_id is None:
            self._audit_sync_state()
            self._edit_sessions_dashboard_message(chat_id, message_id, page_index=page_index)
            self._telegram.answer_callback_query(callback_query_id, "Refreshed.")
            return

        assert target_chat_id is not None and target_message_thread_id is not None
        binding = self._binding_by_topic(int(target_chat_id), int(target_message_thread_id))
        if binding is None or not self._is_primary_binding(binding):
            self._telegram.answer_callback_query(callback_query_id, "This topic is no longer bound.")
            return

        if action == "refresh":
            self._audit_sync_state()
            self._edit_sessions_dashboard_message(chat_id, message_id, page_index=page_index)
            self._telegram.answer_callback_query(callback_query_id, "Refreshed.")
            return

        if action == "new":
            self._start_new_thread(
                binding.chat_id,
                binding.message_thread_id,
                binding,
                thread_title=DEFAULT_NEW_THREAD_TITLE,
            )
            self._edit_sessions_dashboard_message(chat_id, message_id, page_index=page_index)
            self._telegram.answer_callback_query(callback_query_id, "Started a new thread.")
            return

        if action == "unbind":
            dashboard_entry = self._session_dashboard_entry_for_binding(binding)
            text, reply_markup = render_unbind_confirmation(
                dashboard_entry,
                page_index=page_index,
            )
            self._telegram.edit_message_text(
                chat_id,
                message_id,
                text,
                reply_markup=reply_markup,
            )
            self._telegram.answer_callback_query(callback_query_id)
            return

        if action == "unbind_confirm":
            self._unbind_topic(binding)
            self._edit_sessions_dashboard_message(chat_id, message_id, page_index=page_index)
            self._telegram.answer_callback_query(callback_query_id, "Unbound.")
            return

        if action == "restore":
            callback_text = self._restore_binding_from_dashboard(binding)
            if callback_text == "Nothing to restore.":
                self._telegram.answer_callback_query(callback_query_id, callback_text)
                return
            self._edit_sessions_dashboard_message(chat_id, message_id, page_index=page_index)
            self._telegram.answer_callback_query(callback_query_id, callback_text)
            return

        if action == "live":
            try:
                self._start_live_view(
                    binding,
                    target_chat_id=chat_id,
                    target_message_thread_id=message_thread_id,
                )
            except ScreenshotCaptureError as exc:
                self._telegram.answer_callback_query(callback_query_id, f"Live view failed: {exc}")
                return
            self._telegram.answer_callback_query(callback_query_id, "Live view started.")
            return

        if action == "screenshot":
            try:
                self._send_screenshot_for_binding(
                    binding,
                    target_chat_id=chat_id,
                    target_message_thread_id=message_thread_id,
                )
            except ScreenshotCaptureError as exc:
                self._telegram.answer_callback_query(callback_query_id, f"Screenshot failed: {exc}")
                return
            self._telegram.answer_callback_query(callback_query_id, "Sent screenshot.")
            return

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
        self._state.delete_voice_prompt_view(chat_id, message_thread_id)
        self._clear_interactive_prompt_topic(
            chat_id,
            message_thread_id,
            codex_thread_id=previous_thread_id,
        )
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

    def _handle_interactive_prompt_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        parsed_callback = parse_interactive_callback(str(update["data"]))
        if parsed_callback is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown prompt action.")
            return

        prompt_view = self._state.get_interactive_prompt_view(chat_id, message_thread_id)
        if (
            prompt_view is None
            or prompt_view.message_id != message_id
            or prompt_view.prompt_id != str(parsed_callback["prompt_id"])
        ):
            self._telegram.answer_callback_query(callback_query_id, "This prompt is stale.")
            return

        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is None or not self._is_primary_binding(binding):
            self._state.delete_interactive_prompt_view(chat_id, message_thread_id)
            self._telegram.answer_callback_query(callback_query_id, "This topic is no longer bound.")
            return

        session = self._interactive_prompt_sessions.get(prompt_view.prompt_id)
        if session is None:
            self._state.delete_interactive_prompt_view(chat_id, message_thread_id)
            self._telegram.edit_message_text(
                chat_id,
                message_id,
                "This prompt expired after the gateway restarted. Continue it from Codex App.",
                reply_markup=None,
            )
            self._telegram.answer_callback_query(callback_query_id, "This prompt expired.")
            return

        try:
            prompt_update = apply_interactive_callback(
                session,
                action=str(parsed_callback["action"]),
                value=parsed_callback["value"],
            )
        except ValueError:
            self._telegram.answer_callback_query(callback_query_id, "That prompt choice is no longer available.")
            return

        self._apply_interactive_prompt_update(
            binding,
            prompt_id=prompt_view.prompt_id,
            message_id=prompt_view.message_id,
            update=prompt_update,
        )
        self._telegram.answer_callback_query(
            callback_query_id,
            prompt_update.toast_text,
        )

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

    def _handle_remote_action_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        from_user_id = int(update["from_user_id"])
        parsed = parse_remote_action_callback(str(update["data"]))
        if parsed is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown remote action.")
            return

        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is None:
            self._telegram.answer_callback_query(callback_query_id, "This topic is no longer bound.")
            return
        if binding.binding_status != ACTIVE_BINDING_STATUS:
            if self._is_primary_binding(binding):
                self._offer_restore_prompt(binding)
            self._telegram.answer_callback_query(callback_query_id, "This topic needs restore first.")
            return

        action = str(parsed["action"])
        if action == "interrupt":
            self._handle_remote_interrupt_action(
                callback_query_id,
                binding,
                turn_id=str(parsed["turn_id"]),
            )
            return
        if action == "continue":
            self._handle_remote_continue_action(
                callback_query_id,
                binding,
                turn_id=str(parsed["turn_id"]),
            )
            return
        if action == "prompt":
            self._handle_remote_prompt_action(
                callback_query_id,
                binding,
                prompt_id=str(parsed["prompt_id"]),
                choice=str(parsed["choice"]),
            )
            return
        if action == "retry":
            self._handle_remote_retry_action(
                callback_query_id,
                binding,
                from_user_id=from_user_id,
                telegram_update_id=int(update["update_id"]),
                history_index_text=str(parsed["history_index"]),
            )
            return
        self._telegram.answer_callback_query(callback_query_id, "Unknown remote action.")

    def _handle_remote_interrupt_action(
        self,
        callback_query_id: str,
        binding: Binding,
        *,
        turn_id: str,
    ) -> None:
        pending_turn = self._state.get_pending_turn(binding.codex_thread_id)
        if pending_turn is None or pending_turn.turn_id != turn_id:
            self._telegram.answer_callback_query(callback_query_id, "This control is stale.")
            return
        turn_result = self._codex.interrupt_turn(binding.codex_thread_id, turn_id)
        self._state.delete_pending_turn(binding.codex_thread_id)
        primary_binding = self._state.get_binding_by_thread(binding.codex_thread_id)
        self._clear_interactive_prompt_topic(
            primary_binding.chat_id,
            primary_binding.message_thread_id,
            codex_thread_id=binding.codex_thread_id,
        )
        queued_count = self._queued_inbound_count(binding.codex_thread_id)
        latest_summary = _latest_visible_summary(self._codex.list_events(binding.codex_thread_id))
        thread = self._codex.read_thread(binding.codex_thread_id)
        for target in self._targets_for_thread(binding.codex_thread_id):
            self._set_topic_status_override(
                target.chat_id,
                target.message_thread_id,
                TOPIC_STATUS_FAILED,
            )
            self._clear_typing_state(target.chat_id, target.message_thread_id)
            if target.binding_status != ACTIVE_BINDING_STATUS:
                continue
            self._sync_status_bubble_for_binding(
                target,
                thread=thread,
                pending_turn=None,
                turn_result=turn_result,
                latest_summary=latest_summary,
                queued_count=queued_count,
            )
        self._telegram.answer_callback_query(callback_query_id, "Stopped.")

    def _handle_remote_continue_action(
        self,
        callback_query_id: str,
        binding: Binding,
        *,
        turn_id: str,
    ) -> None:
        pending_turn = self._state.get_pending_turn(binding.codex_thread_id)
        if pending_turn is None or pending_turn.turn_id != turn_id:
            self._telegram.answer_callback_query(callback_query_id, "This control is stale.")
            return
        if pending_turn.waiting_for_approval:
            self._telegram.answer_callback_query(callback_query_id, "Use the approval buttons first.")
            return
        self._send_typing_if_due(binding.chat_id, binding.message_thread_id, force=True)
        try:
            self._codex.steer_turn(
                StartedTurn(
                    thread_id=binding.codex_thread_id,
                    text="Continue.",
                ),
                expected_turn_id=pending_turn.turn_id,
                on_progress=lambda: self._send_typing_if_due(
                    binding.chat_id,
                    binding.message_thread_id,
                ),
            )
        except Exception as exc:
            self._telegram.answer_callback_query(callback_query_id, _steer_callback_text(exc))
            return
        self._telegram.answer_callback_query(callback_query_id, "Steered.")

    def _handle_remote_prompt_action(
        self,
        callback_query_id: str,
        binding: Binding,
        *,
        prompt_id: str,
        choice: str,
    ) -> None:
        prompt = next(
            (
                candidate
                for candidate in self._codex.list_pending_prompts(binding.codex_thread_id)
                if candidate.prompt_id == prompt_id
            ),
            None,
        )
        if prompt is None:
            self._telegram.answer_callback_query(callback_query_id, "This approval request is no longer pending.")
            return
        session = self._interactive_prompt_sessions.get(prompt_id)
        if session is None:
            session = start_interactive_prompt_session(prompt)
            self._interactive_prompt_sessions[prompt_id] = session
        try:
            prompt_update = apply_interactive_callback(
                session,
                action="choose",
                value=choice,
            )
        except ValueError as exc:
            self._telegram.answer_callback_query(callback_query_id, str(exc))
            return

        prompt_view = self._state.get_interactive_prompt_view(binding.chat_id, binding.message_thread_id)
        if prompt_view is None or prompt_view.prompt_id != prompt_id:
            try:
                primary_binding = self._state.get_binding_by_thread(binding.codex_thread_id)
            except KeyError:
                primary_binding = binding
            prompt_view = self._state.get_interactive_prompt_view(
                primary_binding.chat_id,
                primary_binding.message_thread_id,
            )
            if prompt_view is not None and prompt_view.prompt_id == prompt_id:
                self._apply_interactive_prompt_update(
                    primary_binding,
                    prompt_id=prompt_id,
                    message_id=prompt_view.message_id,
                    update=prompt_update,
                )
            elif prompt_update.response_payload is not None:
                self._codex.respond_interactive_prompt(prompt_id, prompt_update.response_payload)
                self._interactive_prompt_sessions.pop(prompt_id, None)
        else:
            self._apply_interactive_prompt_update(
                binding,
                prompt_id=prompt_id,
                message_id=prompt_view.message_id,
                update=prompt_update,
            )
        self._telegram.answer_callback_query(callback_query_id, prompt_update.toast_text)

    def _handle_remote_retry_action(
        self,
        callback_query_id: str,
        binding: Binding,
        *,
        from_user_id: int,
        telegram_update_id: int,
        history_index_text: str,
    ) -> None:
        if self._state.get_pending_turn(binding.codex_thread_id) is not None:
            self._telegram.answer_callback_query(callback_query_id, "Codex is still answering right now.")
            return
        try:
            history_index = int(history_index_text)
        except ValueError:
            self._telegram.answer_callback_query(callback_query_id, "Invalid retry item.")
            return
        history = self._state.list_topic_history(binding.chat_id, binding.message_thread_id, limit=history_index + 1)
        if history_index < 0 or history_index >= len(history):
            self._telegram.answer_callback_query(callback_query_id, "That message is no longer available.")
            return
        recalled = history[history_index]
        self._enqueue_bound_inbound(
            binding,
            telegram_update_id=telegram_update_id,
            from_user_id=from_user_id,
            text=recalled.text,
            local_image_paths=recalled.local_image_paths,
        )
        self._telegram.answer_callback_query(callback_query_id, "Queued.")

    def _handle_verbose_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        parsed_callback = parse_verbose_callback(str(update["data"]))
        if parsed_callback is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown verbose action.")
            return
        if parsed_callback["action"] == "dismiss":
            self._telegram.edit_message_reply_markup(chat_id, message_id, None)
            self._telegram.answer_callback_query(callback_query_id, "Dismissed.")
            return

        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is None:
            self._telegram.answer_callback_query(callback_query_id, "This topic is not bound to any Codex thread.")
            return

        updated_binding = self._save_binding(
            replace(
                binding,
                sync_mode=str(parsed_callback["mode"]),
            )
        )
        text, reply_markup = build_verbose_picker(updated_binding.sync_mode)
        self._telegram.edit_message_text(
            chat_id,
            message_id,
            text,
            reply_markup=reply_markup,
        )
        self._telegram.answer_callback_query(
            callback_query_id,
            notification_mode_button_text(updated_binding.sync_mode),
        )

    def _handle_recall_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_id = int(update["message_id"])
        action = parse_recall_callback(str(update["data"]))
        if action != "dismiss":
            self._telegram.answer_callback_query(callback_query_id, "Unknown recall action.")
            return
        self._telegram.edit_message_reply_markup(chat_id, message_id, None)
        self._telegram.answer_callback_query(callback_query_id, "Dismissed.")

    def _handle_send_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        parsed_callback = parse_send_callback(str(update["data"]))
        send_view = self._state.get_send_view(chat_id, message_thread_id)
        if parsed_callback is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown send action.")
            return
        if send_view is None or send_view.message_id != message_id:
            self._telegram.answer_callback_query(callback_query_id, "This send browser is stale.")
            return

        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is None or not self._is_primary_binding(binding) or binding.codex_thread_id != send_view.codex_thread_id:
            self._state.delete_send_view(chat_id, message_thread_id)
            self._telegram.answer_callback_query(callback_query_id, "This send browser is stale.")
            return

        action = str(parsed_callback["action"])
        index = parsed_callback["index"]
        if action == "cancel":
            self._telegram.edit_message_reply_markup(chat_id, message_id, None)
            self._state.delete_send_view(chat_id, message_thread_id)
            self._telegram.answer_callback_query(callback_query_id, "Cancelled.")
            return
        if action == "root":
            self._show_send_browser(
                SendViewState(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    message_id=message_id,
                    codex_thread_id=send_view.codex_thread_id,
                    project_root=send_view.project_root,
                )
            )
            self._telegram.answer_callback_query(callback_query_id)
            return
        if action == "back":
            if send_view.selected_relative_path is not None:
                self._show_send_browser(
                    SendViewState(
                        chat_id=chat_id,
                        message_thread_id=message_thread_id,
                        message_id=message_id,
                        codex_thread_id=send_view.codex_thread_id,
                        project_root=send_view.project_root,
                        current_relative_path=send_view.current_relative_path,
                        page_index=send_view.page_index,
                        query=send_view.query,
                    )
                )
            else:
                current_path = Path(send_view.current_relative_path)
                parent_path = "." if current_path in {Path("."), Path("")} else str(current_path.parent)
                self._show_send_browser(
                    SendViewState(
                        chat_id=chat_id,
                        message_thread_id=message_thread_id,
                        message_id=message_id,
                        codex_thread_id=send_view.codex_thread_id,
                        project_root=send_view.project_root,
                        current_relative_path=parent_path if parent_path else ".",
                    )
                )
            self._telegram.answer_callback_query(callback_query_id)
            return
        if action == "page":
            self._show_send_browser(
                SendViewState(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    message_id=message_id,
                    codex_thread_id=send_view.codex_thread_id,
                    project_root=send_view.project_root,
                    current_relative_path=send_view.current_relative_path,
                    page_index=int(index or 0),
                    query=send_view.query,
                )
            )
            self._telegram.answer_callback_query(callback_query_id)
            return

        listing = self._send_listing_for_view(send_view)
        if action == "enter":
            if index is None or index < 0 or index >= len(listing.entries):
                self._telegram.answer_callback_query(callback_query_id, "This send browser is stale.")
                return
            entry = listing.entries[int(index)]
            if not entry.is_dir:
                self._telegram.answer_callback_query(callback_query_id, "That entry is not a folder.")
                return
            self._show_send_browser(
                SendViewState(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    message_id=message_id,
                    codex_thread_id=send_view.codex_thread_id,
                    project_root=send_view.project_root,
                    current_relative_path=entry.relative_path,
                )
            )
            self._telegram.answer_callback_query(callback_query_id)
            return
        if action == "preview":
            if index is None or index < 0 or index >= len(listing.entries):
                self._telegram.answer_callback_query(callback_query_id, "This send browser is stale.")
                return
            entry = listing.entries[int(index)]
            if entry.is_dir:
                self._telegram.answer_callback_query(callback_query_id, "That entry is not a file.")
                return
            self._show_send_preview(
                SendViewState(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    message_id=message_id,
                    codex_thread_id=send_view.codex_thread_id,
                    project_root=send_view.project_root,
                    current_relative_path=send_view.current_relative_path,
                    page_index=send_view.page_index,
                    query=send_view.query,
                    selected_relative_path=entry.relative_path,
                )
            )
            self._telegram.answer_callback_query(callback_query_id)
            return
        if action in {"doc", "photo"}:
            if send_view.selected_relative_path is None:
                self._telegram.answer_callback_query(callback_query_id, "This send browser is stale.")
                return
            preview = build_send_preview(send_view.project_root, send_view.selected_relative_path)
            file_path = Path(send_view.project_root) / preview.relative_path
            if action == "photo":
                if not preview.send_as_photo:
                    self._telegram.answer_callback_query(callback_query_id, "This file cannot be sent as a photo.")
                    return
                self._telegram.send_photo_file(
                    chat_id,
                    message_thread_id,
                    file_path,
                    caption=preview.relative_path,
                )
                callback_text = "Sent as photo."
            else:
                self._telegram.send_document_file(
                    chat_id,
                    message_thread_id,
                    file_path,
                    caption=preview.relative_path,
                )
                callback_text = "Sent as document."
            self._telegram.edit_message_reply_markup(chat_id, message_id, None)
            self._state.delete_send_view(chat_id, message_thread_id)
            self._telegram.answer_callback_query(callback_query_id, callback_text)
            return

        self._telegram.answer_callback_query(callback_query_id, "Unknown send action.")

    def _send_project_root(self, binding: Binding) -> str | None:
        if binding.project_id:
            return binding.project_id
        thread = self._codex.read_thread(binding.codex_thread_id)
        return thread.cwd or None

    def _send_listing_for_view(self, send_view: SendViewState):
        if send_view.query:
            return search_project_files(
                send_view.project_root,
                send_view.query,
                page_index=send_view.page_index,
                page_size=6,
            )
        return browse_project_files(
            send_view.project_root,
            current_relative_path=send_view.current_relative_path,
            page_index=send_view.page_index,
            page_size=6,
        )

    def _show_send_browser(self, send_view: SendViewState) -> None:
        listing = self._send_listing_for_view(send_view)
        project_name = Path(send_view.project_root).name or send_view.project_root
        text, reply_markup = build_send_browser_page(
            project_name=project_name,
            listing=listing,
        )
        self._telegram.edit_message_text(
            send_view.chat_id,
            send_view.message_id,
            text,
            reply_markup=reply_markup,
        )
        self._state.upsert_send_view(
            SendViewState(
                chat_id=send_view.chat_id,
                message_thread_id=send_view.message_thread_id,
                message_id=send_view.message_id,
                codex_thread_id=send_view.codex_thread_id,
                project_root=send_view.project_root,
                current_relative_path=listing.current_relative_path,
                page_index=listing.page_index,
                query=listing.query,
            )
        )

    def _show_send_preview(self, send_view: SendViewState) -> None:
        if send_view.selected_relative_path is None:
            raise ValueError("selected_relative_path is required for preview mode.")
        preview = build_send_preview(send_view.project_root, send_view.selected_relative_path)
        project_name = Path(send_view.project_root).name or send_view.project_root
        text, reply_markup = build_send_preview_page(
            project_name=project_name,
            preview=preview,
        )
        self._telegram.edit_message_text(
            send_view.chat_id,
            send_view.message_id,
            text,
            reply_markup=reply_markup,
        )
        self._state.upsert_send_view(send_view)

    def _open_send_browser(
        self,
        binding: Binding,
        *,
        query: str,
    ) -> None:
        project_root = self._send_project_root(binding)
        if not project_root:
            self._telegram.send_message(
                binding.chat_id,
                binding.message_thread_id,
                "This topic is bound, but the Codex project path is missing.",
            )
            return

        project_root_path = Path(project_root).expanduser().resolve()
        normalized_query = query.strip()
        initial_view = SendViewState(
            chat_id=binding.chat_id,
            message_thread_id=binding.message_thread_id,
            message_id=0,
            codex_thread_id=binding.codex_thread_id,
            project_root=str(project_root_path),
        )
        if normalized_query:
            candidate = (project_root_path / normalized_query).resolve()
            try:
                candidate.relative_to(project_root_path)
            except ValueError:
                candidate = None
            if candidate is not None and candidate.is_dir():
                initial_view = SendViewState(
                    chat_id=binding.chat_id,
                    message_thread_id=binding.message_thread_id,
                    message_id=0,
                    codex_thread_id=binding.codex_thread_id,
                    project_root=str(project_root_path),
                    current_relative_path=str(candidate.relative_to(project_root_path)).replace("\\", "/") or ".",
                )
                listing = self._send_listing_for_view(initial_view)
                text, reply_markup = build_send_browser_page(
                    project_name=project_root_path.name or str(project_root_path),
                    listing=listing,
                )
                message_id = self._telegram.send_message(
                    binding.chat_id,
                    binding.message_thread_id,
                    text,
                    reply_markup=reply_markup,
                )
                self._state.upsert_send_view(replace(initial_view, message_id=message_id, page_index=listing.page_index))
                return
            if candidate is not None and candidate.is_file():
                preview = build_send_preview(
                    project_root_path,
                    str(candidate.relative_to(project_root_path)).replace("\\", "/"),
                )
                text, reply_markup = build_send_preview_page(
                    project_name=project_root_path.name or str(project_root_path),
                    preview=preview,
                )
                message_id = self._telegram.send_message(
                    binding.chat_id,
                    binding.message_thread_id,
                    text,
                    reply_markup=reply_markup,
                )
                self._state.upsert_send_view(
                    replace(
                        initial_view,
                        message_id=message_id,
                        selected_relative_path=preview.relative_path,
                    )
                )
                return
            initial_view = replace(initial_view, query=normalized_query)

        listing = self._send_listing_for_view(initial_view)
        text, reply_markup = build_send_browser_page(
            project_name=project_root_path.name or str(project_root_path),
            listing=listing,
        )
        message_id = self._telegram.send_message(
            binding.chat_id,
            binding.message_thread_id,
            text,
            reply_markup=reply_markup,
        )
        self._state.upsert_send_view(
            replace(
                initial_view,
                message_id=message_id,
                page_index=listing.page_index,
                current_relative_path=listing.current_relative_path,
                query=listing.query,
            )
        )

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
        self._state.delete_voice_prompt_view(topic_project.chat_id, topic_project.message_thread_id)
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

    def _show_toolbar(
        self,
        chat_id: int,
        message_thread_id: int,
        *,
        message_id: int | None = None,
    ) -> None:
        binding = self._binding_by_topic(chat_id, message_thread_id)
        topic_project = self._state.get_topic_project(chat_id, message_thread_id)
        project_id = topic_project.project_id if topic_project is not None else None
        codex_thread_id: str | None = None
        if binding is not None:
            thread = self._codex.read_thread(binding.codex_thread_id)
            project_id = binding.project_id or thread.cwd or project_id
            codex_thread_id = binding.codex_thread_id
        text = render_toolbar_text(
            project_id=project_id,
            codex_thread_id=codex_thread_id,
        )
        reply_markup = build_toolbar_markup(
            self._toolbar_config,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            project_id=project_id,
        )
        existing_view = self._state.get_toolbar_view(chat_id, message_thread_id)
        target_message_id = message_id or (existing_view.message_id if existing_view is not None else None)
        try:
            if target_message_id is None:
                target_message_id = self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    text,
                    reply_markup=reply_markup,
                )
            else:
                self._telegram.edit_message_text(
                    chat_id,
                    target_message_id,
                    text,
                    reply_markup=reply_markup,
                )
        except Exception:
            target_message_id = self._telegram.send_message(
                chat_id,
                message_thread_id,
                text,
                reply_markup=reply_markup,
            )

        self._state.upsert_toolbar_view(
            ToolbarViewState(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                message_id=target_message_id,
                codex_thread_id=codex_thread_id,
                project_id=project_id,
            )
        )

    def _handle_toolbar_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        action_name = parse_toolbar_callback(str(update["data"]))
        if action_name is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown toolbar action.")
            return

        toolbar_view = self._state.get_toolbar_view(chat_id, message_thread_id)
        if toolbar_view is None or toolbar_view.message_id != message_id:
            self._telegram.answer_callback_query(callback_query_id, "This toolbar is stale.")
            return

        action = self._toolbar_config.actions.get(action_name)
        if action is None:
            self._telegram.answer_callback_query(callback_query_id, "This toolbar action is unavailable.")
            return

        if action.action_type == "builtin":
            if action.payload == "dismiss":
                self._state.delete_toolbar_view(chat_id, message_thread_id)
                self._telegram.edit_message_reply_markup(chat_id, message_id, None)
                self._telegram.answer_callback_query(callback_query_id, "Dismissed.")
                return
            if action.payload == "refresh":
                self._show_toolbar(chat_id, message_thread_id, message_id=message_id)
                self._telegram.answer_callback_query(callback_query_id, "Refreshed.")
                return
            self._telegram.answer_callback_query(callback_query_id, "Unknown toolbar action.")
            return

        if action.action_type == "gateway_command":
            parsed_command = _parse_command(f"/gateway {action.payload}")
            if parsed_command is None:
                self._telegram.answer_callback_query(callback_query_id, "Invalid toolbar command.")
                return
            self._handle_command(
                update,
                command_name=parsed_command[0],
                command_args=parsed_command[1],
            )
            self._telegram.answer_callback_query(callback_query_id, f"Ran {parsed_command[0]}.")
            return

        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is not None and binding.binding_status != ACTIVE_BINDING_STATUS:
            if self._is_primary_binding(binding):
                self._offer_restore_prompt(binding)
            self._telegram.answer_callback_query(callback_query_id, "This topic needs restore first.")
            return

        if action.action_type == "thread_text":
            if binding is None:
                topic_project = self._state.get_topic_project(chat_id, message_thread_id)
                self._open_project_picker(
                    chat_id=chat_id,
                    message_thread_id=message_thread_id,
                    topic_name=topic_project.topic_name if topic_project else None,
                    pending_update_id=int(update["update_id"]),
                    pending_user_id=int(update["from_user_id"]),
                    pending_text=action.payload,
                )
                self._telegram.answer_callback_query(callback_query_id, "Choose a project.")
                return
            self._enqueue_bound_inbound(
                binding,
                telegram_update_id=int(update["update_id"]),
                from_user_id=int(update["from_user_id"]),
                text=action.payload,
            )
            self._telegram.answer_callback_query(callback_query_id, "Queued.")
            return

        if action.action_type == "steer_template":
            if binding is None:
                self._telegram.answer_callback_query(callback_query_id, "No active Codex thread in this topic.")
                return
            pending_turn = self._state.get_pending_turn(binding.codex_thread_id)
            if pending_turn is None:
                self._telegram.answer_callback_query(callback_query_id, "Codex is not answering right now.")
                return
            self._send_typing_if_due(chat_id, message_thread_id, force=True)
            try:
                self._codex.steer_turn(
                    StartedTurn(
                        thread_id=binding.codex_thread_id,
                        text=action.payload,
                    ),
                    expected_turn_id=pending_turn.turn_id,
                    on_progress=lambda: self._send_typing_if_due(chat_id, message_thread_id),
                )
            except Exception as exc:
                self._telegram.answer_callback_query(
                    callback_query_id,
                    _steer_callback_text(exc),
                )
                return
            self._telegram.answer_callback_query(callback_query_id, "Steered.")
            return

        self._telegram.answer_callback_query(callback_query_id, "Unknown toolbar action.")

    def _send_screenshot_for_binding(
        self,
        binding: Binding,
        *,
        target_chat_id: int,
        target_message_thread_id: int,
    ) -> None:
        if self._screenshot_provider is None:
            raise ScreenshotCaptureError("Screenshot capture is not available on this platform.")
        thread = self._codex.read_thread(binding.codex_thread_id)
        project_id = binding.project_id or thread.cwd or None
        capture = self._screenshot_provider.capture_thread(
            thread_id=binding.codex_thread_id,
            thread_title=thread.title,
            project_id=project_id,
        )
        if not capture.file_path.is_file():
            raise ScreenshotCaptureError("Screenshot file is missing.")
        project_name = Path(project_id or "").name or "-"
        caption = f"Screenshot · {project_name} / {thread.title}"
        if capture.send_as_document:
            self._telegram.send_document_file(
                target_chat_id,
                target_message_thread_id,
                capture.file_path,
                caption=caption,
            )
            return
        self._telegram.send_photo_file(
            target_chat_id,
            target_message_thread_id,
            capture.file_path,
            caption=caption,
        )

    def _start_live_view(
        self,
        binding: Binding,
        *,
        target_chat_id: int,
        target_message_thread_id: int,
        existing_message_id: int | None = None,
    ) -> bool:
        if self._screenshot_provider is None:
            raise ScreenshotCaptureError("Screenshot capture is not available on this platform.")
        now = time.monotonic()
        thread = self._codex.read_thread(binding.codex_thread_id)
        project_id = binding.project_id or thread.cwd or None
        capture = self._screenshot_provider.capture_thread(
            thread_id=binding.codex_thread_id,
            thread_title=thread.title,
            project_id=project_id,
        )
        if not capture.file_path.is_file():
            raise ScreenshotCaptureError("Screenshot file is missing.")
        caption = render_live_view_caption(
            project_name=Path(project_id or "").name or "-",
            thread_title=thread.title,
        )
        reply_markup = build_live_view_markup()
        capture_hash = capture_hash_for_path(capture.file_path)
        current_view = self._state.get_live_view(target_chat_id, target_message_thread_id)
        if existing_message_id is None and current_view is not None:
            existing_message_id = current_view.message_id
        if existing_message_id is None:
            message_id = self._telegram.send_photo_file(
                target_chat_id,
                target_message_thread_id,
                capture.file_path,
                caption=caption,
            )
            self._telegram.edit_message_reply_markup(
                target_chat_id,
                message_id,
                reply_markup,
            )
        else:
            message_id = existing_message_id
            self._telegram.edit_message_photo_file(
                target_chat_id,
                message_id,
                capture.file_path,
                caption=caption,
                reply_markup=reply_markup,
            )
        self._state.upsert_live_view(
            LiveViewState(
                chat_id=target_chat_id,
                message_thread_id=target_message_thread_id,
                message_id=message_id,
                codex_thread_id=binding.codex_thread_id,
                project_id=project_id,
                started_at=now,
                next_refresh_at=now + self._config.live_view_interval_seconds,
                last_capture_hash=capture_hash,
            )
        )
        return existing_message_id is None

    def _stop_live_view(
        self,
        chat_id: int,
        message_thread_id: int,
        *,
        status_suffix: str,
    ) -> None:
        live_view = self._state.get_live_view(chat_id, message_thread_id)
        if live_view is None:
            return
        thread_title = live_view.codex_thread_id
        try:
            thread = self._codex.read_thread(live_view.codex_thread_id)
        except Exception:
            thread = None
        if thread is not None:
            thread_title = thread.title
        project_name = Path(live_view.project_id or "").name or "-"
        caption = f"{render_live_view_caption(project_name=project_name, thread_title=thread_title)}\n{status_suffix}"
        try:
            self._telegram.edit_message_caption(
                chat_id,
                live_view.message_id,
                caption,
                reply_markup=build_live_view_markup(active=False),
            )
        except Exception:
            pass
        self._state.delete_live_view(chat_id, message_thread_id)

    def _refresh_live_view(
        self,
        live_view: LiveViewState,
        *,
        force: bool = False,
    ) -> bool:
        if self._screenshot_provider is None:
            raise ScreenshotCaptureError("Screenshot capture is not available on this platform.")
        binding = self._binding_by_topic(live_view.chat_id, live_view.message_thread_id)
        if binding is None or binding.codex_thread_id != live_view.codex_thread_id:
            self._stop_live_view(
                live_view.chat_id,
                live_view.message_thread_id,
                status_suffix="Stopped.",
            )
            return False
        if binding.binding_status != ACTIVE_BINDING_STATUS:
            self._stop_live_view(
                live_view.chat_id,
                live_view.message_thread_id,
                status_suffix="Topic unavailable.",
            )
            return False
        now = time.monotonic()
        if not force and now - live_view.started_at >= self._config.live_view_timeout_seconds:
            self._stop_live_view(
                live_view.chat_id,
                live_view.message_thread_id,
                status_suffix="Timed out.",
            )
            return False
        if not force and now < live_view.next_refresh_at:
            return False
        thread = self._codex.read_thread(live_view.codex_thread_id)
        project_id = binding.project_id or thread.cwd or live_view.project_id
        capture = self._screenshot_provider.capture_thread(
            thread_id=live_view.codex_thread_id,
            thread_title=thread.title,
            project_id=project_id,
        )
        if not capture.file_path.is_file():
            raise ScreenshotCaptureError("Screenshot file is missing.")
        capture_hash = capture_hash_for_path(capture.file_path)
        next_refresh_at = now + self._config.live_view_interval_seconds
        if not force and capture_hash == live_view.last_capture_hash:
            self._state.upsert_live_view(
                LiveViewState(
                    chat_id=live_view.chat_id,
                    message_thread_id=live_view.message_thread_id,
                    message_id=live_view.message_id,
                    codex_thread_id=live_view.codex_thread_id,
                    project_id=project_id,
                    started_at=live_view.started_at,
                    next_refresh_at=next_refresh_at,
                    last_capture_hash=live_view.last_capture_hash,
                )
            )
            return False
        self._telegram.edit_message_photo_file(
            live_view.chat_id,
            live_view.message_id,
            capture.file_path,
            caption=render_live_view_caption(
                project_name=Path(project_id or "").name or "-",
                thread_title=thread.title,
            ),
            reply_markup=build_live_view_markup(),
        )
        self._state.upsert_live_view(
            LiveViewState(
                chat_id=live_view.chat_id,
                message_thread_id=live_view.message_thread_id,
                message_id=live_view.message_id,
                codex_thread_id=live_view.codex_thread_id,
                project_id=project_id,
                started_at=live_view.started_at,
                next_refresh_at=next_refresh_at,
                last_capture_hash=capture_hash,
            )
        )
        return True

    def _tick_live_views(self) -> None:
        for live_view in self._state.list_live_views():
            try:
                self._refresh_live_view(live_view)
            except Exception:
                continue

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
                _commands_text(
                    self._config,
                    self._state.list_passthrough_commands(),
                ),
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

        if command_name == "upgrade":
            try:
                text = render_upgrade_text(
                    discover_upgrade_diagnostics(
                        start_path=Path(__file__).resolve(),
                    )
                )
            except Exception as exc:
                text = f"Upgrade diagnostics failed: {exc}"
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                text,
            )
            return

        if command_name == "status":
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                self._status_text(binding, chat_id, message_thread_id),
            )
            return

        if command_name == "recall":
            history = self._state.list_topic_history(chat_id, message_thread_id, limit=10)
            if not history:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    "No recent topic messages yet.",
                )
                return
            text, reply_markup = render_recall_prompt(history)
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                text,
                reply_markup=reply_markup,
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
            text, reply_markup = self._render_sessions_dashboard(page_index=0)
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                text,
                reply_markup=reply_markup,
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

        if command_name == "toolbar":
            self._show_toolbar(chat_id, message_thread_id)
            return

        if command_name == "msg":
            self._handle_mailbox_command(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                binding=binding,
                command_args=command_args,
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

        if command_name == "screenshot":
            if binding is None:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    "This topic is not bound to any Codex thread.",
                )
                return
            try:
                self._send_screenshot_for_binding(
                    binding,
                    target_chat_id=chat_id,
                    target_message_thread_id=message_thread_id,
                )
            except ScreenshotCaptureError as exc:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    f"Failed to capture screenshot: {exc}",
                )
            return

        if command_name == "panes":
            if binding is None:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    "This topic is not bound to any Codex thread.",
                )
                return
            thread = self._codex.read_thread(binding.codex_thread_id)
            project_id = binding.project_id or thread.cwd or ""
            project_name = Path(project_id).name or project_id or "-"
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                render_panes_compatibility(
                    bound_thread=thread,
                    project_name=project_name,
                    project_threads=project_threads_for_panes(
                        bound_thread=thread,
                        loaded_threads=self._codex.list_loaded_threads(),
                    ),
                ),
            )
            return

        if command_name == "shell":
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
            self._handle_shell_command(
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                binding=binding,
                command_args=command_args,
            )
            return

        if command_name == "live":
            if binding is None:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    "This topic is not bound to any Codex thread.",
                )
                return
            try:
                self._start_live_view(
                    binding,
                    target_chat_id=chat_id,
                    target_message_thread_id=message_thread_id,
                )
            except ScreenshotCaptureError as exc:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    f"Failed to start live view: {exc}",
                )
            return

        if command_name == "send":
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
            self._open_send_browser(binding, query=command_args)
            return

        if command_name == "verbose":
            if binding is None:
                self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    "This topic is not bound to any Codex thread.",
                )
                return
            text, reply_markup = build_verbose_picker(binding.sync_mode)
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                text,
                reply_markup=reply_markup,
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

    def _refresh_command_menu_for_passthrough(self, text: str) -> None:
        command_name = _extract_passthrough_command_name(text)
        if command_name is None:
            return
        if not self._state.remember_passthrough_command(command_name):
            return
        try:
            register_bot_commands_if_changed(
                telegram=self._telegram,
                state=self._state,
                config=self._config,
            )
        except TelegramApiError:
            return

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
        self._state.delete_send_view(chat_id, message_thread_id)
        self._state.delete_live_view(chat_id, message_thread_id)
        self._state.delete_voice_prompt_view(chat_id, message_thread_id)
        self._state.delete_shell_view(chat_id, message_thread_id)
        self._clear_interactive_prompt_topic(
            chat_id,
            message_thread_id,
            codex_thread_id=previous_thread_id,
        )
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
            self._state.delete_send_view(target.chat_id, target.message_thread_id)
            self._state.delete_live_view(target.chat_id, target.message_thread_id)
            self._state.delete_voice_prompt_view(target.chat_id, target.message_thread_id)
            self._state.delete_shell_view(target.chat_id, target.message_thread_id)
            self._clear_interactive_prompt_topic(
                target.chat_id,
                target.message_thread_id,
            )
            self._state.delete_status_bubble_view(target.chat_id, target.message_thread_id)
            self._status_bubble_renders.pop((target.chat_id, target.message_thread_id), None)
            self._state.delete_topic_history(target.chat_id, target.message_thread_id)
            self._clear_typing_state(target.chat_id, target.message_thread_id)
            self._clear_topic_status_override(target.chat_id, target.message_thread_id)

        self._state.delete_pending_turn(binding.codex_thread_id)
        self._codex.clear_pending_prompts(binding.codex_thread_id)
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

    def _queued_inbound_count(self, codex_thread_id: str) -> int:
        return sum(
            1
            for inbound_message in self._state.list_pending_inbound()
            if inbound_message.codex_thread_id == codex_thread_id
        )

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
        notification_mode = normalize_notification_mode(binding.sync_mode)
        pending_suffix = ""
        if pending_turn is not None:
            pending_suffix = " (waiting for approval)" if pending_turn.waiting_for_approval else " (running)"
        return (
            f"{prefix}Topic status\n\n"
            f"Project: `{project_name}`\n"
            f"Thread title: `{thread.title}`\n"
            f"Thread id: `{binding.codex_thread_id}`\n"
            f"Topic id: `{binding.message_thread_id}`\n"
            f"Notification mode: `{notification_mode}`\n"
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

    def _handle_shell_command(
        self,
        *,
        chat_id: int,
        message_thread_id: int,
        binding: Binding,
        command_args: str,
    ) -> None:
        request = parse_shell_request(command_args)
        if request.mode == "help":
            self._clear_shell_view(chat_id, message_thread_id)
            self._telegram.send_message(chat_id, message_thread_id, render_shell_help())
            return

        thread = self._codex.read_thread(binding.codex_thread_id)
        cwd = binding.project_id or thread.cwd or ""
        if not cwd:
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                "No project directory is available for this topic.",
            )
            return
        project_name = Path(cwd).name or cwd or "-"

        if request.mode == "raw":
            self._clear_shell_view(chat_id, message_thread_id)
            self._execute_shell_command(
                binding=binding,
                chat_id=chat_id,
                message_thread_id=message_thread_id,
                command=request.payload,
                cwd=cwd,
                project_name=project_name,
            )
            return

        if self._shell_suggester is None:
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                "Shell command suggestions are not configured. Use `/gateway shell !<command>` for raw execution.",
            )
            return

        try:
            suggestion = self._shell_suggester.suggest_command(
                description=request.payload,
                cwd=cwd,
                project_name=project_name,
                thread_title=thread.title,
            )
        except Exception as exc:
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                f"Shell command suggestion failed: {exc}",
            )
            return
        current_view = self._state.get_shell_view(chat_id, message_thread_id)
        draft_view = ShellSuggestionView(
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            message_id=current_view.message_id if current_view is not None else 0,
            codex_thread_id=binding.codex_thread_id,
            cwd=cwd,
            project_name=project_name,
            thread_title=thread.title,
            suggestion=suggestion,
        )
        text, reply_markup = render_shell_suggestion(draft_view)
        try:
            if current_view is not None:
                message_id = current_view.message_id
                self._telegram.edit_message_text(
                    chat_id,
                    message_id,
                    text,
                    reply_markup=reply_markup,
                )
            else:
                message_id = self._telegram.send_message(
                    chat_id,
                    message_thread_id,
                    text,
                    reply_markup=reply_markup,
                )
        except Exception as exc:
            if self._mark_binding_deleted_if_missing_topic(binding, exc):
                self._state.delete_shell_view(chat_id, message_thread_id)
                return
            message_id = self._telegram.send_message(
                chat_id,
                message_thread_id,
                text,
                reply_markup=reply_markup,
            )
        self._state.upsert_shell_view(
            replace(
                draft_view,
                message_id=message_id,
            )
        )

    def _handle_shell_callback(self, update: dict[str, object]) -> None:
        callback_query_id = str(update["callback_query_id"])
        chat_id = int(update["chat_id"])
        message_thread_id = int(update["message_thread_id"])
        message_id = int(update["message_id"])
        action = parse_shell_callback(str(update["data"]))
        if action is None:
            self._telegram.answer_callback_query(callback_query_id, "Unknown shell action.")
            return
        shell_view = self._state.get_shell_view(chat_id, message_thread_id)
        if shell_view is None or shell_view.message_id != message_id:
            self._telegram.answer_callback_query(callback_query_id, "This shell suggestion is stale.")
            return
        binding = self._binding_by_topic(chat_id, message_thread_id)
        if binding is None:
            self._state.delete_shell_view(chat_id, message_thread_id)
            self._telegram.answer_callback_query(callback_query_id, "This topic is no longer bound.")
            return
        if action == "cancel":
            self._state.delete_shell_view(chat_id, message_thread_id)
            try:
                self._telegram.edit_message_text(
                    chat_id,
                    message_id,
                    "Shell command suggestion cancelled.",
                    reply_markup=None,
                )
            except Exception as exc:
                if not self._mark_binding_deleted_if_missing_topic(binding, exc):
                    raise
            self._telegram.answer_callback_query(callback_query_id, "Cancelled.")
            return

        self._state.delete_shell_view(chat_id, message_thread_id)
        self._telegram.answer_callback_query(callback_query_id, "Running.")
        self._execute_shell_command(
            binding=binding,
            chat_id=chat_id,
            message_thread_id=message_thread_id,
            command=shell_view.suggestion.command,
            cwd=shell_view.cwd,
            project_name=shell_view.project_name,
            existing_message_id=message_id,
        )

    def _clear_shell_view(self, chat_id: int, message_thread_id: int) -> None:
        shell_view = self._state.get_shell_view(chat_id, message_thread_id)
        if shell_view is not None:
            try:
                self._telegram.edit_message_reply_markup(chat_id, shell_view.message_id, None)
            except Exception:
                pass
        self._state.delete_shell_view(chat_id, message_thread_id)

    def _execute_shell_command(
        self,
        *,
        binding: Binding,
        chat_id: int,
        message_thread_id: int,
        command: str,
        cwd: str,
        project_name: str,
        existing_message_id: int | None = None,
    ) -> None:
        try:
            result = self._shell_runner.run(
                command=command,
                cwd=cwd,
                timeout_seconds=self._config.shell_command_timeout_seconds,
            )
            text = render_shell_result(result, project_name=project_name)
        except Exception as exc:
            text = f"Shell command execution failed: {exc}"
        try:
            if existing_message_id is not None:
                self._telegram.edit_message_text(
                    chat_id,
                    existing_message_id,
                    text,
                    reply_markup=None,
                )
            else:
                self._telegram.send_message(chat_id, message_thread_id, text)
        except Exception as exc:
            if self._mark_binding_deleted_if_missing_topic(binding, exc):
                return
            self._telegram.send_message(chat_id, message_thread_id, text)

    def _handle_mailbox_command(
        self,
        *,
        chat_id: int,
        message_thread_id: int,
        binding: Binding | None,
        command_args: str,
    ) -> None:
        if binding is None:
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                "This topic is not bound to any Codex thread.",
            )
            return

        command = parse_mailbox_command(command_args)
        if command.action == "help":
            self._telegram.send_message(chat_id, message_thread_id, render_mailbox_help())
            return

        thread = self._codex.read_thread(binding.codex_thread_id)

        if command.action == "peers":
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                render_mailbox_peers(self._mailbox_peers(current_thread_id=thread.thread_id)),
            )
            return

        if command.action == "send":
            recipient_thread_id = command.recipient_thread_id or ""
            if not recipient_thread_id or not command.body:
                self._telegram.send_message(chat_id, message_thread_id, "Usage: /gateway msg send <thread-id> <body>")
                return
            if recipient_thread_id == thread.thread_id:
                self._telegram.send_message(chat_id, message_thread_id, "Cannot send a mailbox message to the current thread.")
                return
            try:
                recipient_binding = self._state.get_binding_by_thread(recipient_thread_id)
            except KeyError:
                self._telegram.send_message(chat_id, message_thread_id, f"Recipient thread `{recipient_thread_id}` is not bound.")
                return
            recipient_thread = self._codex.read_thread(recipient_thread_id)
            message = self._state.create_mailbox_message(
                from_thread_id=thread.thread_id,
                to_thread_id=recipient_thread_id,
                body=command.body,
            )
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                render_mailbox_send_ack(message_id=message.message_id, recipient_title=recipient_thread.title),
            )
            if recipient_binding.binding_status == ACTIVE_BINDING_STATUS:
                self._telegram.send_message(
                    recipient_binding.chat_id,
                    recipient_binding.message_thread_id,
                    render_mailbox_recipient_notice(message_id=message.message_id, sender_title=thread.title),
                )
            return

        if command.action == "broadcast":
            if not command.body:
                self._telegram.send_message(chat_id, message_thread_id, "Usage: /gateway msg broadcast <body>")
                return
            peers = [
                peer
                for peer in self._mailbox_peers(current_thread_id=thread.thread_id)
                if not peer.is_current
            ]
            if not peers:
                self._telegram.send_message(chat_id, message_thread_id, "No bound peer threads available for broadcast.")
                return
            for peer in peers:
                message = self._state.create_mailbox_message(
                    from_thread_id=thread.thread_id,
                    to_thread_id=peer.thread_id,
                    body=command.body,
                )
                recipient_binding = self._state.get_binding_by_thread(peer.thread_id)
                if recipient_binding.binding_status == ACTIVE_BINDING_STATUS:
                    self._telegram.send_message(
                        recipient_binding.chat_id,
                        recipient_binding.message_thread_id,
                        render_mailbox_recipient_notice(message_id=message.message_id, sender_title=thread.title),
                    )
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                f"Queued {len(peers)} mailbox message(s) for broadcast.",
            )
            return

        if command.action == "inbox":
            inbox = self._state.list_mailbox_inbox(thread.thread_id)
            if not inbox:
                self._telegram.send_message(chat_id, message_thread_id, "Mailbox inbox is empty.")
                return
            lines = ["Mailbox inbox:"]
            for message in inbox:
                sender = self._codex.read_thread(message.from_thread_id)
                lines.append(f"- `{message.message_id}` from `{sender.title}` · {message.status}")
            self._telegram.send_message(chat_id, message_thread_id, "\n".join(lines))
            return

        if command.action == "read":
            if not command.message_id:
                self._telegram.send_message(chat_id, message_thread_id, "Usage: /gateway msg read <message-id>")
                return
            message = self._state.mark_mailbox_read(command.message_id, codex_thread_id=thread.thread_id)
            if message is None:
                self._telegram.send_message(chat_id, message_thread_id, f"Mailbox message `{command.message_id}` was not found.")
                return
            sender = self._codex.read_thread(message.from_thread_id)
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                f"Mailbox message `{message.message_id}`\nFrom: `{sender.title}`\nStatus: `{message.status}`\n\n{message.body}",
            )
            return

        if command.action == "reply":
            if not command.message_id or not command.body:
                self._telegram.send_message(chat_id, message_thread_id, "Usage: /gateway msg reply <message-id> <body>")
                return
            original = self._state.get_mailbox_message(command.message_id)
            if original is None or original.to_thread_id != thread.thread_id:
                self._telegram.send_message(chat_id, message_thread_id, f"Mailbox message `{command.message_id}` was not found.")
                return
            try:
                recipient_binding = self._state.get_binding_by_thread(original.from_thread_id)
            except KeyError:
                self._telegram.send_message(chat_id, message_thread_id, f"Reply target `{original.from_thread_id}` is not bound.")
                return
            recipient_thread = self._codex.read_thread(original.from_thread_id)
            reply = self._state.create_mailbox_message(
                from_thread_id=thread.thread_id,
                to_thread_id=original.from_thread_id,
                body=command.body,
                reply_to_message_id=original.message_id,
            )
            self._telegram.send_message(
                chat_id,
                message_thread_id,
                render_mailbox_send_ack(message_id=reply.message_id, recipient_title=recipient_thread.title),
            )
            if recipient_binding.binding_status == ACTIVE_BINDING_STATUS:
                self._telegram.send_message(
                    recipient_binding.chat_id,
                    recipient_binding.message_thread_id,
                    render_mailbox_recipient_notice(message_id=reply.message_id, sender_title=thread.title),
                )
            return

        self._telegram.send_message(chat_id, message_thread_id, render_mailbox_help())

    def _mailbox_peers(self, *, current_thread_id: str) -> list[MailboxPeer]:
        loaded_threads = {
            thread.thread_id: thread
            for thread in self._codex.list_loaded_threads()
        }
        peers: list[MailboxPeer] = []
        for binding in self._state.list_bindings():
            if binding.binding_status != ACTIVE_BINDING_STATUS:
                continue
            thread = loaded_threads.get(binding.codex_thread_id)
            if thread is None:
                continue
            project_name = Path(binding.project_id or thread.cwd or "").name or "-"
            peers.append(
                MailboxPeer(
                    thread_id=thread.thread_id,
                    title=thread.title,
                    project_name=project_name,
                    status=thread.status,
                    is_current=thread.thread_id == current_thread_id,
                )
            )
        peers.sort(
            key=lambda peer: (
                not peer.is_current,
                peer.project_name.lower(),
                peer.title.lower(),
                peer.thread_id.lower(),
            )
        )
        return peers

    def _deliver_mailbox_once(self) -> None:
        for message in self._state.list_pending_mailbox_messages():
            pending_turn = self._state.get_pending_turn(message.to_thread_id)
            if pending_turn is not None:
                continue
            try:
                binding = self._state.get_binding_by_thread(message.to_thread_id)
            except KeyError:
                continue
            if binding.binding_status != ACTIVE_BINDING_STATUS:
                continue
            recipient_thread = self._codex.read_thread(message.to_thread_id)
            if recipient_thread.status not in {"idle", "notLoaded"}:
                continue
            sender_thread = self._codex.read_thread(message.from_thread_id)
            sender_project_name = Path(sender_thread.cwd or "").name or "-"
            self._send_typing_if_due(binding.chat_id, binding.message_thread_id, force=True)
            turn_result = self._codex.start_turn(
                StartedTurn(
                    thread_id=message.to_thread_id,
                    text=render_mailbox_delivery_text(
                        message_id=message.message_id,
                        sender_title=sender_thread.title,
                        sender_project_name=sender_project_name,
                        body=message.body,
                    ),
                )
            )
            self._state.upsert_pending_turn(
                PendingTurn(
                    codex_thread_id=message.to_thread_id,
                    chat_id=binding.chat_id,
                    message_thread_id=binding.message_thread_id,
                    turn_id=turn_result.turn_id,
                    waiting_for_approval=turn_result.waiting_for_approval,
                )
            )
            self._state.mark_mailbox_delivered(message.message_id)
            return

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

    def _edit_sessions_dashboard_message(
        self,
        chat_id: int,
        message_id: int,
        *,
        page_index: int,
    ) -> None:
        text, reply_markup = self._render_sessions_dashboard(page_index=page_index)
        self._telegram.edit_message_text(
            chat_id,
            message_id,
            text,
            reply_markup=reply_markup,
        )

    def _render_sessions_dashboard(self, *, page_index: int) -> tuple[str, dict[str, object]]:
        bindings = sorted(
            self._state.list_bindings(),
            key=lambda item: ((item.project_id or ""), (item.topic_name or ""), item.codex_thread_id),
        )
        if not bindings:
            return build_sessions_dashboard([], page_index=page_index)

        return build_sessions_dashboard(
            [self._session_dashboard_entry_for_binding(binding) for binding in bindings],
            page_index=page_index,
            pending_jobs=tuple(
                f"- thread `{topic_creation_job.codex_thread_id}` -> chat `{topic_creation_job.chat_id}`"
                for topic_creation_job in self._state.list_topic_creation_jobs()
            ),
        )

    def _session_dashboard_entry_for_binding(self, binding: Binding) -> SessionsDashboardEntry:
        loaded_threads = {thread.thread_id: thread for thread in self._codex.list_loaded_threads()}
        pending_turn = self._state.get_pending_turn(binding.codex_thread_id)
        thread = loaded_threads.get(binding.codex_thread_id)
        topic_name = strip_topic_status_prefix(binding.topic_name or "").strip()
        parsed_topic = _parse_topic_name(topic_name) if topic_name else None
        project_name = (
            Path(binding.project_id or (thread.cwd if thread else "") or "").name
            or (parsed_topic[0] if parsed_topic else "-")
        )
        thread_title = thread.title if thread is not None else (parsed_topic[1] if parsed_topic else binding.codex_thread_id)
        warning_text = self._session_dashboard_warning_text(binding, thread)
        return SessionsDashboardEntry(
            chat_id=binding.chat_id,
            message_thread_id=binding.message_thread_id,
            topic_name=topic_name or format_topic_name(binding.project_id or (thread.cwd if thread else ""), thread_title),
            project_name=project_name,
            thread_title=thread_title,
            codex_thread_id=binding.codex_thread_id,
            thread_status=self._session_dashboard_thread_status(binding, thread, pending_turn),
            notification_mode=normalize_notification_mode(binding.sync_mode),
            mirror_count=len(self._state.list_mirror_bindings_for_thread(binding.codex_thread_id)),
            status_icon=self._session_dashboard_status_icon(binding, thread, pending_turn),
            warning_text=warning_text,
            mirror_descriptions=tuple(
                (
                    f"mirror chat `{mirror_binding.chat_id}` "
                    f"topic `{mirror_binding.message_thread_id}`"
                )
                for mirror_binding in sorted(
                    self._state.list_mirror_bindings_for_thread(binding.codex_thread_id),
                    key=lambda item: (item.chat_id, item.message_thread_id),
                )
            ),
        )

    @staticmethod
    def _session_dashboard_thread_status(
        binding: Binding,
        thread: CodexThread | None,
        pending_turn: PendingTurn | None,
    ) -> str:
        if binding.binding_status == CLOSED_BINDING_STATUS:
            return "closed"
        if binding.binding_status == DELETED_BINDING_STATUS:
            return "deleted"
        if pending_turn is not None and pending_turn.waiting_for_approval:
            return "approval"
        if pending_turn is not None:
            return "running"
        if thread is None:
            return "notLoaded"
        return thread.status

    @staticmethod
    def _session_dashboard_status_icon(
        binding: Binding,
        thread: CodexThread | None,
        pending_turn: PendingTurn | None,
    ) -> str:
        if binding.binding_status == DELETED_BINDING_STATUS:
            return "🔴"
        if binding.binding_status == CLOSED_BINDING_STATUS:
            return "⚫"
        if pending_turn is not None and pending_turn.waiting_for_approval:
            return "🟠"
        if thread is None:
            return "⚪"
        return "🟢"

    @staticmethod
    def _session_dashboard_warning_text(
        binding: Binding,
        thread: CodexThread | None,
    ) -> str | None:
        if binding.binding_status == CLOSED_BINDING_STATUS:
            return "Topic was closed in Telegram."
        if binding.binding_status == DELETED_BINDING_STATUS:
            return "Telegram topic is missing and can be recreated."
        if thread is None:
            return "Codex thread is not loaded in the app."
        return None

    def _restore_binding_from_dashboard(self, binding: Binding) -> str:
        issue_kind = self._restore_issue_for_binding(binding)
        if issue_kind is None:
            return "Nothing to restore."

        if issue_kind == RESTORE_ISSUE_CLOSED:
            thread = self._codex.read_thread(binding.codex_thread_id)
            topic_name = format_topic_name(binding.project_id or thread.cwd, thread.title)
            try:
                self._telegram.edit_forum_topic(
                    binding.chat_id,
                    binding.message_thread_id,
                    topic_name,
                )
            except Exception as exc:
                if not is_topic_edit_permission_error(exc):
                    if self._mark_binding_deleted_if_missing_topic(binding, exc):
                        return "This topic is no longer reachable."
                    raise
            restored_binding = self._save_binding(
                replace(
                    binding,
                    topic_name=topic_name,
                    binding_status=ACTIVE_BINDING_STATUS,
                )
            )
            self._touch_topic_lifecycle(restored_binding.codex_thread_id, completed_at=None)
            self._clear_topic_status_override(binding.chat_id, binding.message_thread_id)
            return "Restored."

        if issue_kind == RESTORE_ISSUE_DELETED:
            self._service.recreate_topic(binding.codex_thread_id)
            return "Recreated."

        return "Nothing to restore."


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
_CALLBACK_VERBOSE_PREFIX = "gw:verbose:"
_CALLBACK_RECALL_PREFIX = "gw:recall:"
_CALLBACK_SEND_PREFIX = "gw:send:"
_CALLBACK_PROMPT_PREFIX = "gw:prompt:"
_CALLBACK_VOICE_PREFIX = "gw:voice:"
_CALLBACK_TOOLBAR_PREFIX = "gw:toolbar:"
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
    _BotCommand("upgrade", "Show plugin version and upgrade instructions"),
    _BotCommand("recall", "Recall recent topic messages"),
    _BotCommand("history", "Show paginated history for this Codex thread"),
    _BotCommand("resume", "Resume another Codex thread from this project"),
    _BotCommand("restore", "Show recovery options for this topic"),
    _BotCommand("unbind", "Detach this Telegram topic from its Codex thread"),
    _BotCommand("bindings", "List Codex thread to Telegram topic bindings", aliases=("sessions",)),
    _BotCommand("create_thread", "Create a new Codex thread in this topic", aliases=("new", "start")),
    _BotCommand("screenshot", "Capture the current Codex App window for this thread"),
    _BotCommand("panes", "Show the Codex App thread summary for tmux-style pane compatibility"),
    _BotCommand("shell", "Suggest or run shell commands in the bound project"),
    _BotCommand("msg", "Use the inter-agent mailbox command family"),
    _BotCommand("live", "Start or refresh a live Codex App window feed"),
    _BotCommand("send", "Browse project files and send one back to Telegram"),
    _BotCommand("verbose", "Change supplemental Telegram notification mode"),
    _BotCommand("project", "Choose or switch the Codex project for this topic"),
    _BotCommand("status", "Show the current topic binding and thread status"),
    _BotCommand("sync", "Audit bindings and recover deleted topics"),
    _BotCommand("toolbar", "Show or refresh the topic action bar"),
    _BotCommand("help", "Show available gateway commands", aliases=("commands",)),
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


def _commands_text(
    config: GatewayConfig,
    observed_passthrough_commands: tuple[str, ...],
) -> str:
    lines = ["Available gateway commands:"]
    lines.append("/gateway <subcommand> - Run a gateway control action")
    lines.append("")
    lines.append("Gateway subcommands:")
    for command in _GATEWAY_SUBCOMMANDS:
        lines.append(f"/gateway {command.name} - {command.description}")
    lines.append("")
    lines.append("Telegram menu commands:")
    for command_name, description in build_bot_commands(
        config,
        observed_passthrough_commands=observed_passthrough_commands,
    ):
        lines.append(f"/{command_name} - {description}")
    if not observed_passthrough_commands and not config.telegram_menu_passthrough_commands:
        lines.append("Additional pass-through commands appear here after you use them or configure them.")
    lines.append("")
    lines.append("Compatibility aliases inside `/gateway`: new, start, sessions, commands")
    lines.append("All other slash commands are passed through to the bound Codex thread unchanged.")
    return "\n".join(lines)


def _extract_passthrough_command_name(text: str) -> str | None:
    match = _COMMAND_RE.match(text.strip())
    if match is None:
        return None
    command_name = match.group(1).lower()
    if command_name == "gateway":
        return None
    return command_name


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
    return history_entry_label(entry, limit=limit)


def _latest_visible_summary(events: list) -> str | None:
    for event in reversed(events):
        kind = getattr(event, "kind", None)
        if kind not in {"assistant_message", "completion_summary", "tool_batch"}:
            continue
        text = " ".join(str(getattr(event, "text", "")).split()).strip()
        if not text:
            continue
        if kind == "tool_batch":
            last_line = str(getattr(event, "text", "")).splitlines()[-1].strip()
            text = " ".join(last_line.split())
            if text.startswith("• "):
                text = text[2:]
        if len(text) <= 120:
            return text
        return text[:119].rstrip() + "…"
    return None


def _is_renderable_event_kind(kind: object) -> bool:
    return kind in {"assistant_message", "tool_batch", "completion_summary"}


def _is_artifact_event_kind(kind: object) -> bool:
    return kind in {"artifact_photo", "artifact_document"}


def _event_turn_id(event_id: str) -> str | None:
    parts = event_id.split(":", 2)
    if len(parts) < 3:
        return None
    return parts[1]
