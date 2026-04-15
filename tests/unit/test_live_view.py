from pathlib import Path

from codex_telegram_gateway.live_view import (
    CALLBACK_LIVE_VIEW_PREFIX,
    LiveViewState,
    build_live_view_markup,
    capture_hash_for_path,
    parse_live_view_callback,
    render_live_view_caption,
)


def test_build_live_view_markup_for_active_session() -> None:
    assert build_live_view_markup() == {
        "inline_keyboard": [
            [
                {"text": "Refresh", "callback_data": f"{CALLBACK_LIVE_VIEW_PREFIX}refresh"},
                {"text": "Stop", "callback_data": f"{CALLBACK_LIVE_VIEW_PREFIX}stop"},
            ]
        ]
    }


def test_build_live_view_markup_for_inactive_session() -> None:
    assert build_live_view_markup(active=False) == {
        "inline_keyboard": [
            [
                {"text": "Start live", "callback_data": f"{CALLBACK_LIVE_VIEW_PREFIX}start"},
            ]
        ]
    }


def test_parse_live_view_callback_accepts_known_actions() -> None:
    assert parse_live_view_callback("gw:live:refresh") == "refresh"
    assert parse_live_view_callback("gw:live:stop") == "stop"
    assert parse_live_view_callback("gw:live:start") == "start"


def test_parse_live_view_callback_rejects_unknown_actions() -> None:
    assert parse_live_view_callback("gw:live:nope") is None
    assert parse_live_view_callback("gw:toolbar:refresh") is None


def test_render_live_view_caption_uses_project_and_thread_names() -> None:
    assert render_live_view_caption(project_name="gateway-project", thread_title="thread-1") == (
        "Live view · gateway-project / thread-1"
    )


def test_capture_hash_for_path_changes_when_file_changes(tmp_path) -> None:
    capture_path = tmp_path / "capture.png"
    capture_path.write_bytes(b"\x89PNG\r\n\x1a\nfirst")
    first_hash = capture_hash_for_path(capture_path)

    capture_path.write_bytes(b"\x89PNG\r\n\x1a\nsecond")
    second_hash = capture_hash_for_path(capture_path)

    assert first_hash != second_hash


def test_live_view_state_defaults() -> None:
    state = LiveViewState(
        chat_id=-100100,
        message_thread_id=77,
        message_id=1,
        codex_thread_id="thread-1",
        project_id="/Users/kangmo/sacle/src/gateway-project",
        started_at=10.0,
    )

    assert state.next_refresh_at == 0.0
    assert state.last_capture_hash == ""
