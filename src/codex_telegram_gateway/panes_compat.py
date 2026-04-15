from collections.abc import Sequence

from codex_telegram_gateway.models import CodexThread


def project_threads_for_panes(
    *,
    bound_thread: CodexThread,
    loaded_threads: Sequence[CodexThread],
) -> tuple[CodexThread, ...]:
    """Return the loaded threads relevant to `/panes` compatibility output."""
    project_id = bound_thread.cwd
    ordered_threads: list[CodexThread] = [bound_thread]
    seen_thread_ids = {bound_thread.thread_id}

    if not project_id:
        return tuple(ordered_threads)

    matching_threads = sorted(
        (
            thread
            for thread in loaded_threads
            if thread.cwd == project_id and thread.thread_id not in seen_thread_ids
        ),
        key=lambda thread: ((thread.title or thread.thread_id).lower(), thread.thread_id.lower()),
    )
    ordered_threads.extend(matching_threads)
    return tuple(ordered_threads)


def render_panes_compatibility(
    *,
    bound_thread: CodexThread,
    project_name: str,
    project_threads: Sequence[CodexThread],
) -> str:
    """Render the Codex-App-native compatibility message for `/panes`."""
    current_title = bound_thread.title or bound_thread.thread_id
    lines = [
        "`/panes` is not available in Codex App mode.",
        "",
        "Current topic thread:",
        f"- `{current_title}` in `{project_name}`",
        "",
        "Loaded threads in this project:",
    ]
    if not project_threads:
        lines.append("- No loaded threads in this project right now")
    else:
        for thread in project_threads:
            thread_title = thread.title or thread.thread_id
            if thread.thread_id == bound_thread.thread_id:
                suffix = f"this topic, {thread.status}"
            else:
                suffix = thread.status
            lines.append(f"- `{thread_title}` ({suffix})")
    lines.extend(
        [
            "",
            "Use `/gateway threads` for a full list, `/gateway screenshot` for a capture, or `/gateway live` for a live view.",
        ]
    )
    return "\n".join(lines)
