from codex_telegram_gateway.models import (
    CLOSED_BINDING_STATUS,
    Binding,
    CodexProject,
    HistoryViewState,
    InboundMessage,
    StatusBubbleViewState,
    OutboundMessage,
    PendingTurn,
    RestoreViewState,
    ResumeViewState,
    SendViewState,
    TopicCreationJob,
    TopicLifecycle,
    TopicHistoryEntry,
    TopicProject,
)
from codex_telegram_gateway.state import SqliteGatewayState


def test_sqlite_state_persists_binding_queue_and_cursor(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    binding = Binding(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        topic_name="(gateway-project) thread-1",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )
    inbound = InboundMessage(
        telegram_update_id=2,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        codex_thread_id="thread-1",
        text="Please continue.",
        local_image_paths=("/tmp/example-image.png",),
    )

    state.create_binding(binding)
    state.enqueue_inbound(inbound)
    state.mark_event_seen("thread-1", "thread-1:turn-1:item-1")
    state.set_telegram_cursor(9)

    assert state.get_binding_by_thread("thread-1") == binding
    assert state.get_binding_by_topic(-100100, 77) == binding
    assert state.list_pending_inbound() == [inbound]
    assert state.has_seen_event("thread-1", "thread-1:turn-1:item-1") is True
    assert state.get_telegram_cursor() == 9


def test_sqlite_state_routes_by_topic_id_even_if_topic_name_changes(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    original = Binding(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        topic_name="original-topic-name",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )
    renamed = Binding(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        topic_name="renamed-topic-name",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )

    state.create_binding(original)
    state.create_binding(renamed)

    assert state.get_binding_by_thread("thread-1") == renamed
    assert state.get_binding_by_topic(-100100, 77) == renamed


def test_sqlite_state_persists_binding_status_updates(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    active = Binding(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        topic_name="topic-name",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )
    closed = Binding(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        topic_name="topic-name",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
        binding_status=CLOSED_BINDING_STATUS,
    )

    state.create_binding(active)
    state.create_binding(closed)

    assert state.get_binding_by_thread("thread-1") == closed
    assert state.get_binding_by_topic(-100100, 77) == closed


def test_sqlite_state_deletes_detached_binding_runtime_state(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    primary = Binding(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        topic_name="(gateway-project) thread-1",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )
    mirror = Binding(
        codex_thread_id="thread-1",
        chat_id=-100200,
        message_thread_id=88,
        topic_name="(gateway-project) thread-1",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )
    inbound = InboundMessage(
        telegram_update_id=5,
        chat_id=-100100,
        message_thread_id=77,
        from_user_id=111,
        codex_thread_id="thread-1",
        text="queued message",
    )
    outbound = OutboundMessage(
        codex_thread_id="thread-1",
        event_id="event-1",
        telegram_message_ids=(10,),
        text="assistant output",
    )

    state.create_binding(primary)
    state.upsert_mirror_binding(mirror)
    state.enqueue_inbound(inbound)
    state.upsert_outbound_message(outbound)
    state.upsert_mirror_outbound_message(outbound, chat_id=-100200, message_thread_id=88)
    state.record_topic_history(-100100, 77, text="recent")
    state.record_topic_history(-100200, 88, text="mirror recent")

    state.delete_pending_inbound_for_thread("thread-1")
    state.delete_outbound_messages("thread-1")
    state.delete_mirror_outbound_messages("thread-1", chat_id=-100200)
    state.delete_topic_history(-100100, 77)
    state.delete_topic_history(-100200, 88)
    state.delete_mirror_binding("thread-1", chat_id=-100200)
    state.delete_binding("thread-1")

    assert state.list_pending_inbound() == []
    assert state.get_outbound_message("thread-1", "event-1") is None
    assert state.get_mirror_outbound_message(
        "thread-1",
        "event-1",
        chat_id=-100200,
        message_thread_id=88,
    ) is None
    assert state.list_topic_history(-100100, 77) == []
    assert state.list_topic_history(-100200, 88) == []
    assert state.get_binding_by_topic(-100100, 77) is None
    assert state.get_mirror_binding_by_topic(-100200, 88) is None
    try:
        state.get_binding_by_thread("thread-1")
    except KeyError:
        pass
    else:
        raise AssertionError("Expected deleted binding lookup to raise KeyError")


def test_sqlite_state_persists_loaded_projects_and_topic_project_selection(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    project = CodexProject(
        project_id="/Users/kangmo/sacle/src/blink",
        project_name="blink",
    )
    topic_project = TopicProject(
        chat_id=-100100,
        message_thread_id=77,
        topic_name="(blink) Remove browser entitlement",
        project_id=project.project_id,
        picker_message_id=15,
        pending_local_image_paths=("/tmp/example-image.png",),
    )

    state.upsert_project(project)
    state.upsert_topic_project(topic_project)

    assert state.get_project(project.project_id) == project
    assert state.list_projects() == [project]
    assert state.get_topic_project(-100100, 77) == topic_project


def test_sqlite_state_persists_pending_turns(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    pending_turn = PendingTurn(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        turn_id="turn-99",
        waiting_for_approval=True,
    )

    state.upsert_pending_turn(pending_turn)

    assert state.get_pending_turn("thread-1") == pending_turn
    assert state.list_pending_turns() == [pending_turn]

    state.delete_pending_turn("thread-1")

    assert state.get_pending_turn("thread-1") is None


def test_sqlite_state_persists_status_bubble_view(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    bubble_view = StatusBubbleViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=15,
        codex_thread_id="thread-1",
    )

    state.upsert_status_bubble_view(bubble_view)

    assert state.get_status_bubble_view(-100100, 77) == bubble_view

    state.delete_status_bubble_view(-100100, 77)

    assert state.get_status_bubble_view(-100100, 77) is None


def test_sqlite_state_persists_outbound_message_blocks(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    outbound_message = OutboundMessage(
        codex_thread_id="thread-1",
        event_id="thread-1:turn-1:item-1",
        telegram_message_ids=(10, 11),
        text="first block\nsecond block",
        reply_markup={"inline_keyboard": [[{"text": "Ready", "callback_data": "noop"}]]},
    )

    state.upsert_outbound_message(outbound_message)

    assert state.get_outbound_message("thread-1", "thread-1:turn-1:item-1") == outbound_message


def test_sqlite_state_persists_recent_topic_history_with_dedup(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")

    state.record_topic_history(-100100, 77, text="First request")
    state.record_topic_history(-100100, 77, text="First request")
    state.record_topic_history(
        -100100,
        77,
        text="Second request",
        local_image_paths=("/tmp/example-image.png",),
    )

    assert state.list_topic_history(-100100, 77) == [
        TopicHistoryEntry(
            text="Second request",
            local_image_paths=("/tmp/example-image.png",),
        ),
        TopicHistoryEntry(text="First request"),
    ]


def test_sqlite_state_persists_history_view_state(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    history_view = HistoryViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=42,
        codex_thread_id="thread-1",
        page_index=3,
    )

    state.upsert_history_view(history_view)

    assert state.get_history_view(-100100, 77) == history_view

    state.delete_history_view(-100100, 77)

    assert state.get_history_view(-100100, 77) is None


def test_sqlite_state_persists_resume_view_state(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    resume_view = ResumeViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=43,
        project_id="/Users/kangmo/sacle/src/gateway-project",
        page_index=1,
    )

    state.upsert_resume_view(resume_view)

    assert state.get_resume_view(-100100, 77) == resume_view

    state.delete_resume_view(-100100, 77)

    assert state.get_resume_view(-100100, 77) is None


def test_sqlite_state_persists_restore_view_state(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    restore_view = RestoreViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=44,
        codex_thread_id="thread-1",
        issue_kind="closed",
    )

    state.upsert_restore_view(restore_view)

    assert state.get_restore_view(-100100, 77) == restore_view

    state.delete_restore_view(-100100, 77)

    assert state.get_restore_view(-100100, 77) is None


def test_sqlite_state_persists_send_view_state(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    send_view = SendViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=45,
        codex_thread_id="thread-1",
        project_root="/Users/kangmo/sacle/src/gateway-project",
        current_relative_path="docs",
        page_index=1,
        query="note",
        selected_relative_path="docs/notes.txt",
    )

    state.upsert_send_view(send_view)

    assert state.get_send_view(-100100, 77) == send_view

    state.delete_send_view(-100100, 77)

    assert state.get_send_view(-100100, 77) is None


def test_sqlite_state_persists_topic_lifecycle_and_project_activity(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    lifecycle = TopicLifecycle(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        bound_at=1.0,
        last_inbound_at=2.0,
        last_outbound_at=3.0,
        completed_at=4.0,
    )

    state.upsert_topic_lifecycle(lifecycle)
    state.set_topic_project_last_seen(-100100, 88, 9.5)

    assert state.get_topic_lifecycle("thread-1") == lifecycle
    assert state.list_topic_lifecycles() == [lifecycle]
    assert state.get_topic_project_last_seen(-100100, 88) == 9.5
    assert state.list_topic_project_last_seen() == [(-100100, 88, 9.5)]

    state.delete_topic_lifecycle("thread-1")
    state.delete_topic_project_last_seen(-100100, 88)

    assert state.get_topic_lifecycle("thread-1") is None
    assert state.get_topic_project_last_seen(-100100, 88) is None


def test_sqlite_state_prunes_orphan_topic_history(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    state.record_topic_history(-100100, 77, text="keep me")
    state.record_topic_history(-100100, 88, text="delete me")

    state.prune_orphan_topic_history({(-100100, 77)})

    assert state.list_topic_history(-100100, 77) == [TopicHistoryEntry(text="keep me")]
    assert state.list_topic_history(-100100, 88) == []


def test_sqlite_state_persists_mirror_bindings_events_outbound_and_creation_jobs(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    mirror_binding = Binding(
        codex_thread_id="thread-1",
        chat_id=-100200,
        message_thread_id=88,
        topic_name="(gateway-project) thread-1",
        sync_mode="assistant_plus_alerts",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )
    outbound_message = OutboundMessage(
        codex_thread_id="thread-1",
        event_id="event-1",
        telegram_message_ids=(99,),
        text="mirrored reply",
    )
    topic_creation_job = TopicCreationJob(
        codex_thread_id="thread-2",
        chat_id=-100300,
        topic_name="(other-project) untitled",
        project_id="/Users/kangmo/sacle/src/other-project",
        retry_after_at=123.0,
    )

    state.upsert_mirror_binding(mirror_binding)
    state.mark_mirror_event_seen("thread-1", "event-1", chat_id=-100200, message_thread_id=88)
    state.upsert_mirror_outbound_message(
        outbound_message,
        chat_id=-100200,
        message_thread_id=88,
    )
    state.upsert_topic_creation_job(topic_creation_job)

    assert state.get_mirror_binding_by_topic(-100200, 88) == mirror_binding
    assert state.list_mirror_bindings_for_thread("thread-1") == [mirror_binding]
    assert state.has_mirror_seen_event("thread-1", "event-1", chat_id=-100200, message_thread_id=88) is True
    assert state.get_mirror_outbound_message(
        "thread-1",
        "event-1",
        chat_id=-100200,
        message_thread_id=88,
    ) == outbound_message
    assert state.get_topic_creation_job("thread-2", -100300) == topic_creation_job

    state.delete_mirror_seen_event("thread-1", "event-1", chat_id=-100200, message_thread_id=88)
    state.delete_mirror_outbound_messages("thread-1", chat_id=-100200)
    state.delete_topic_creation_job("thread-2", -100300)

    assert state.has_mirror_seen_event("thread-1", "event-1", chat_id=-100200, message_thread_id=88) is False
    assert state.get_mirror_outbound_message(
        "thread-1",
        "event-1",
        chat_id=-100200,
        message_thread_id=88,
    ) is None
    assert state.get_topic_creation_job("thread-2", -100300) is None


def test_sqlite_state_can_delete_seen_events_and_outbound_messages(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")
    state.mark_event_seen("thread-1", "event-1")
    state.upsert_outbound_message(
        OutboundMessage(
            codex_thread_id="thread-1",
            event_id="event-1",
            telegram_message_ids=(7,),
            text="reply",
        )
    )

    state.delete_seen_event("thread-1", "event-1")
    state.delete_outbound_messages("thread-1")

    assert state.has_seen_event("thread-1", "event-1") is False
    assert state.get_outbound_message("thread-1", "event-1") is None


def test_sqlite_state_persists_command_menu_hash_and_passthrough_commands(tmp_path) -> None:
    state = SqliteGatewayState(tmp_path / "gateway.db")

    assert state.remember_passthrough_command("status") is True
    assert state.remember_passthrough_command("status") is False
    assert state.remember_passthrough_command("help") is True
    state.set_registered_command_menu_hash("chat:-100100", "hash-1")

    assert state.list_passthrough_commands() == ("help", "status")
    assert state.get_registered_command_menu_hash("chat:-100100") == "hash-1"
