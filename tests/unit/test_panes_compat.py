from codex_telegram_gateway.models import CodexThread
from codex_telegram_gateway.panes_compat import (
    project_threads_for_panes,
    render_panes_compatibility,
)


def test_project_threads_for_panes_keeps_same_project_and_current_first() -> None:
    bound_thread = CodexThread(
        thread_id="thread-1",
        title="thread-1",
        status="idle",
        cwd="/Users/kangmo/sacle/src/gateway-project",
    )
    loaded_threads = [
        CodexThread(
            thread_id="thread-3",
            title="thread-3",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        ),
        CodexThread(
            thread_id="thread-4",
            title="other-project-thread",
            status="idle",
            cwd="/Users/kangmo/sacle/src/other-project",
        ),
        bound_thread,
        CodexThread(
            thread_id="thread-2",
            title="thread-2",
            status="running",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        ),
    ]

    assert project_threads_for_panes(
        bound_thread=bound_thread,
        loaded_threads=loaded_threads,
    ) == (
        bound_thread,
        CodexThread(
            thread_id="thread-2",
            title="thread-2",
            status="running",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        ),
        CodexThread(
            thread_id="thread-3",
            title="thread-3",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        ),
    )


def test_render_panes_compatibility_reports_loaded_project_threads() -> None:
    bound_thread = CodexThread(
        thread_id="thread-1",
        title="thread-1",
        status="idle",
        cwd="/Users/kangmo/sacle/src/gateway-project",
    )
    project_threads = (
        bound_thread,
        CodexThread(
            thread_id="thread-2",
            title="thread-2",
            status="running",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        ),
        CodexThread(
            thread_id="thread-3",
            title="thread-3",
            status="idle",
            cwd="/Users/kangmo/sacle/src/gateway-project",
        ),
    )

    assert render_panes_compatibility(
        bound_thread=bound_thread,
        project_name="gateway-project",
        project_threads=project_threads,
    ) == (
        "`/panes` is not available in Codex App mode.\n\n"
        "Current topic thread:\n"
        "- `thread-1` in `gateway-project`\n\n"
        "Loaded threads in this project:\n"
        "- `thread-1` (this topic, idle)\n"
        "- `thread-2` (running)\n"
        "- `thread-3` (idle)\n\n"
        "Use `/gateway threads` for a full list, `/gateway screenshot` for a capture, or `/gateway live` for a live view."
    )


def test_project_threads_for_panes_returns_bound_thread_when_project_is_unknown() -> None:
    bound_thread = CodexThread(
        thread_id="thread-1",
        title="thread-1",
        status="idle",
        cwd="",
    )

    assert project_threads_for_panes(
        bound_thread=bound_thread,
        loaded_threads=[
            CodexThread(
                thread_id="thread-2",
                title="thread-2",
                status="running",
                cwd="/Users/kangmo/sacle/src/gateway-project",
            )
        ],
    ) == (bound_thread,)


def test_render_panes_compatibility_handles_empty_project_threads() -> None:
    bound_thread = CodexThread(
        thread_id="thread-1",
        title="thread-1",
        status="idle",
        cwd="/Users/kangmo/sacle/src/gateway-project",
    )

    assert render_panes_compatibility(
        bound_thread=bound_thread,
        project_name="gateway-project",
        project_threads=(),
    ) == (
        "`/panes` is not available in Codex App mode.\n\n"
        "Current topic thread:\n"
        "- `thread-1` in `gateway-project`\n\n"
        "Loaded threads in this project:\n"
        "- No loaded threads in this project right now\n\n"
        "Use `/gateway threads` for a full list, `/gateway screenshot` for a capture, or `/gateway live` for a live view."
    )
