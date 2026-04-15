from codex_telegram_gateway.sessions_dashboard import (
    SessionsDashboardEntry,
    build_sessions_dashboard,
    parse_sessions_callback,
)


def test_build_sessions_dashboard_renders_session_rows_and_footer() -> None:
    text, markup = build_sessions_dashboard(
        [
            SessionsDashboardEntry(
                chat_id=-100100,
                message_thread_id=77,
                topic_name="(gateway-project) thread-1",
                project_name="gateway-project",
                thread_title="thread-1",
                codex_thread_id="thread-1",
                thread_status="idle",
                notification_mode="all",
                mirror_count=1,
                status_icon="🟢",
                warning_text=None,
            )
        ],
        page_index=0,
    )

    assert text == (
        "Gateway sessions\n"
        "Page 1/1 • 1 binding\n\n"
        "1. 🟢 `(gateway-project) thread-1`\n"
        "project `gateway-project` • thread `thread-1`\n"
        "topic `77` • id `thread-1`\n"
        "status `idle` • notify `all`\n"
        "mirrors `1`"
    )
    assert markup == {
        "inline_keyboard": [
            [
                {"text": "↻", "callback_data": "gw:sessions:refresh:0:-100100:77"},
                {"text": "➕", "callback_data": "gw:sessions:new:0:-100100:77"},
                {"text": "✂", "callback_data": "gw:sessions:unbind:0:-100100:77"},
                {"text": "📺", "callback_data": "gw:sessions:live:0:-100100:77"},
                {"text": "📸", "callback_data": "gw:sessions:screenshot:0:-100100:77"},
                {"text": "♻", "callback_data": "gw:sessions:restore:0:-100100:77"},
            ],
            [
                {"text": "Refresh", "callback_data": "gw:sessions:refresh:0"},
                {"text": "Dismiss", "callback_data": "gw:sessions:dismiss"},
            ],
        ]
    }


def test_build_sessions_dashboard_paginates_entries() -> None:
    entries = [
        SessionsDashboardEntry(
            chat_id=-100100,
            message_thread_id=77 + index,
            topic_name=f"(gateway-project) thread-{index + 1}",
            project_name="gateway-project",
            thread_title=f"thread-{index + 1}",
            codex_thread_id=f"thread-{index + 1}",
            thread_status="idle",
            notification_mode="all",
            mirror_count=0,
            status_icon="🟢",
            warning_text="Topic needs recovery." if index == 3 else None,
        )
        for index in range(4)
    ]

    text, markup = build_sessions_dashboard(entries, page_index=1)

    assert "Page 2/2 • 4 bindings" in text
    assert "1. 🟢 `(gateway-project) thread-4`" in text
    assert "warning `Topic needs recovery.`" in text
    assert markup["inline_keyboard"][-2] == [
        {"text": "Prev", "callback_data": "gw:sessions:page:0"},
    ]


def test_parse_sessions_callback_accepts_global_and_targeted_actions() -> None:
    assert parse_sessions_callback("gw:sessions:dismiss") == {
        "action": "dismiss",
        "page_index": 0,
        "chat_id": None,
        "message_thread_id": None,
    }
    assert parse_sessions_callback("gw:sessions:refresh:2") == {
        "action": "refresh",
        "page_index": 2,
        "chat_id": None,
        "message_thread_id": None,
    }
    assert parse_sessions_callback("gw:sessions:restore:1:-100100:77") == {
        "action": "restore",
        "page_index": 1,
        "chat_id": -100100,
        "message_thread_id": 77,
    }
    assert parse_sessions_callback("gw:sessions:broken") is None
