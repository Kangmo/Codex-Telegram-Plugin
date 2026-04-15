from codex_telegram_gateway.history_command import (
    CALLBACK_HISTORY_PREFIX,
    parse_history_callback,
    render_history_page,
)
from codex_telegram_gateway.models import CodexHistoryEntry


def test_render_history_page_defaults_to_latest_page_and_builds_navigation() -> None:
    entries = [
        CodexHistoryEntry(
            entry_id=f"entry-{index}",
            kind="user" if index % 2 == 0 else "assistant",
            text=f"message {index} " + ("x" * 400),
            timestamp="2026-04-15T10:00:00Z",
        )
        for index in range(12)
    ]

    rendered = render_history_page(
        display_name="(gateway-project) thread-1",
        thread_id="thread-1",
        entries=entries,
    )

    assert rendered.total_pages > 1
    assert rendered.page_index == rendered.total_pages - 1
    assert rendered.reply_markup == {
        "inline_keyboard": [
            [
                {"text": "◀ Older", "callback_data": f"{CALLBACK_HISTORY_PREFIX}{rendered.page_index - 1}:thread-1"},
                {"text": f"{rendered.page_index + 1}/{rendered.total_pages}", "callback_data": "tp:noop"},
            ]
        ]
    }


def test_parse_history_callback_rejects_malformed_payloads() -> None:
    assert parse_history_callback("gw:hist:not-a-page:thread-1") is None
    assert parse_history_callback("gw:hist:1") is None
    assert parse_history_callback("gw:other:1:thread-1") is None
    assert parse_history_callback("gw:hist:2:thread-1") == (2, "thread-1")
