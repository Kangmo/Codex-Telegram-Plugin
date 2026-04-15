from codex_telegram_gateway.models import (
    CLOSED_BINDING_STATUS,
    Binding,
    CodexProject,
    InboundMessage,
    OutboundMessage,
    PendingTurn,
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
