from codex_telegram_gateway.status_bubble import StatusBubbleSnapshot, build_status_bubble


def test_build_status_bubble_for_bound_topic_keeps_controls_visible() -> None:
    snapshot = StatusBubbleSnapshot(
        project_name="gateway-project",
        thread_title="Review gateway parity",
        state="running",
        queued_count=2,
        latest_summary="Reviewing the status-bubble design.",
        history_labels=("retry the image flow",),
    )

    text, reply_markup = build_status_bubble(snapshot)

    assert text == (
        "Topic status\n\n"
        "Project: `gateway-project`\n"
        "Thread: `Review gateway parity`\n"
        "State: `running`\n"
        "Queued: `2`\n"
        "Latest: Reviewing the status-bubble design."
    )
    assert reply_markup == {
        "inline_keyboard": [
            [{"text": "⏳ Working", "callback_data": "gw:resp:noop"}],
            [{"text": "↑ retry the image flow", "callback_data": "gw:resp:recall:0"}],
            [
                {"text": "↺ New", "callback_data": "gw:resp:new"},
                {"text": "📁 Project", "callback_data": "gw:resp:project"},
                {"text": "📍 Status", "callback_data": "gw:resp:status"},
                {"text": "🔄 Sync", "callback_data": "gw:resp:sync"},
            ],
        ]
    }
