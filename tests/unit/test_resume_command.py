from codex_telegram_gateway.models import CodexThread
from codex_telegram_gateway.resume_command import (
    CALLBACK_RESUME_CANCEL,
    CALLBACK_RESUME_PAGE_PREFIX,
    CALLBACK_RESUME_PICK_PREFIX,
    parse_resume_page_callback,
    parse_resume_pick_callback,
    render_resume_picker,
)


def test_render_resume_picker_paginates_threads() -> None:
    threads = [
        CodexThread(
            thread_id=f"thread-{index}",
            title=f"thread title {index}",
            status="idle" if index % 2 == 0 else "notLoaded",
            cwd="/tmp/project",
        )
        for index in range(8)
    ]

    text, reply_markup = render_resume_picker(
        project_id="/tmp/project",
        threads=threads,
        page_index=1,
    )

    assert text == (
        "⏪ Resume Codex Thread\n\n"
        "Project: `project`\n"
        "Available threads: `8`\n\n"
        "Choose an existing thread to bind to this topic."
    )
    assert reply_markup == {
        "inline_keyboard": [
            [{"text": "🟢 thread title 6", "callback_data": f"{CALLBACK_RESUME_PICK_PREFIX}thread-6"}],
            [{"text": "💤 thread title 7", "callback_data": f"{CALLBACK_RESUME_PICK_PREFIX}thread-7"}],
            [
                {"text": "◀ Prev", "callback_data": f"{CALLBACK_RESUME_PAGE_PREFIX}0"},
                {"text": "2/2", "callback_data": "tp:noop"},
            ],
            [{"text": "Cancel", "callback_data": CALLBACK_RESUME_CANCEL}],
        ]
    }


def test_parse_resume_callbacks() -> None:
    assert parse_resume_page_callback("gw:resume:page:3") == 3
    assert parse_resume_page_callback("gw:resume:page:not-a-page") is None
    assert parse_resume_pick_callback("gw:resume:pick:thread-9") == "thread-9"
    assert parse_resume_pick_callback("gw:resume:pick:") is None
