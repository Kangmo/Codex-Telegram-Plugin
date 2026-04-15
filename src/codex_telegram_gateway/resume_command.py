from __future__ import annotations

from pathlib import Path

from codex_telegram_gateway.models import CodexThread


CALLBACK_RESUME_PAGE_PREFIX = "gw:resume:page:"
CALLBACK_RESUME_PICK_PREFIX = "gw:resume:pick:"
CALLBACK_RESUME_CANCEL = "gw:resume:cancel"
_THREADS_PER_PAGE = 6


def parse_resume_page_callback(data: str) -> int | None:
    if not data.startswith(CALLBACK_RESUME_PAGE_PREFIX):
        return None
    try:
        return int(data[len(CALLBACK_RESUME_PAGE_PREFIX):])
    except ValueError:
        return None


def parse_resume_pick_callback(data: str) -> str | None:
    if not data.startswith(CALLBACK_RESUME_PICK_PREFIX):
        return None
    thread_id = data[len(CALLBACK_RESUME_PICK_PREFIX):].strip()
    return thread_id or None


def render_resume_picker(
    *,
    project_id: str,
    threads: list[CodexThread],
    page_index: int = 0,
) -> tuple[str, dict[str, object]]:
    """Render a paginated picker of resumable threads for one project."""

    project_name = Path(project_id).name or project_id
    total_pages = max(1, (len(threads) + _THREADS_PER_PAGE - 1) // _THREADS_PER_PAGE)
    normalized_page_index = max(0, min(page_index, total_pages - 1))
    start = normalized_page_index * _THREADS_PER_PAGE
    page_threads = threads[start : start + _THREADS_PER_PAGE]

    text = (
        "⏪ Resume Codex Thread\n\n"
        f"Project: `{project_name}`\n"
        f"Available threads: `{len(threads)}`\n\n"
        "Choose an existing thread to bind to this topic."
    )

    keyboard: list[list[dict[str, str]]] = []
    for thread in page_threads:
        keyboard.append(
            [
                {
                    "text": f"{_thread_status_icon(thread.status)} {thread.title}",
                    "callback_data": f"{CALLBACK_RESUME_PICK_PREFIX}{thread.thread_id}",
                }
            ]
        )

    nav_row: list[dict[str, str]] = []
    if normalized_page_index > 0:
        nav_row.append(
            {
                "text": "◀ Prev",
                "callback_data": f"{CALLBACK_RESUME_PAGE_PREFIX}{normalized_page_index - 1}",
            }
        )
    nav_row.append(
        {
            "text": f"{normalized_page_index + 1}/{total_pages}",
            "callback_data": "tp:noop",
        }
    )
    if normalized_page_index < total_pages - 1:
        nav_row.append(
            {
                "text": "Next ▶",
                "callback_data": f"{CALLBACK_RESUME_PAGE_PREFIX}{normalized_page_index + 1}",
            }
        )
    keyboard.append(nav_row)
    keyboard.append([{"text": "Cancel", "callback_data": CALLBACK_RESUME_CANCEL}])
    return text, {"inline_keyboard": keyboard}


def _thread_status_icon(status: str) -> str:
    if status == "notLoaded":
        return "💤"
    if status == "running":
        return "⏳"
    return "🟢"
