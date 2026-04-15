from dataclasses import dataclass


_SESSIONS_PREFIX = "gw:sessions:"
_TARGETED_ACTIONS = {
    "refresh",
    "new",
    "unbind",
    "unbind_confirm",
    "live",
    "screenshot",
    "restore",
}
_GLOBAL_ACTIONS = {
    "dismiss",
    "page",
    "refresh",
    "unbind_cancel",
}
_PAGE_SIZE = 3


@dataclass(frozen=True)
class SessionsDashboardEntry:
    chat_id: int
    message_thread_id: int
    topic_name: str
    project_name: str
    thread_title: str
    codex_thread_id: str
    thread_status: str
    notification_mode: str
    mirror_count: int
    status_icon: str
    warning_text: str | None = None
    mirror_descriptions: tuple[str, ...] = ()


def build_sessions_dashboard(
    entries: list[SessionsDashboardEntry],
    *,
    page_index: int,
    page_size: int = _PAGE_SIZE,
    pending_jobs: tuple[str, ...] = (),
) -> tuple[str, dict[str, object]]:
    if not entries:
        return (
            "Gateway sessions\n\n"
            "No bound topics yet.\n"
            "Open a Telegram topic and send a message, or use `/gateway create_thread` inside a bound topic.",
            {
                "inline_keyboard": [
                    [
                        {"text": "Refresh", "callback_data": _global_callback("refresh", 0)},
                        {"text": "Dismiss", "callback_data": f"{_SESSIONS_PREFIX}dismiss"},
                    ]
                ]
            },
        )

    total_entries = len(entries)
    total_pages = max(1, (total_entries + page_size - 1) // page_size)
    safe_page_index = min(max(page_index, 0), total_pages - 1)
    page_entries = entries[safe_page_index * page_size : (safe_page_index + 1) * page_size]

    count_label = "binding" if total_entries == 1 else "bindings"
    lines = [
        "Gateway sessions",
        f"Page {safe_page_index + 1}/{total_pages} • {total_entries} {count_label}",
        "",
    ]
    keyboard_rows: list[list[dict[str, str]]] = []

    for display_index, entry in enumerate(page_entries, start=1):
        lines.append(f"{display_index}. {entry.status_icon} `{entry.topic_name}`")
        lines.append(
            f"project `{entry.project_name}` • thread `{entry.thread_title}`"
        )
        lines.append(
            f"topic `{entry.message_thread_id}` • id `{entry.codex_thread_id}`"
        )
        lines.append(
            f"status `{entry.thread_status}` • notify `{entry.notification_mode}`"
        )
        if entry.mirror_count > 0:
            lines.append(f"mirrors `{entry.mirror_count}`")
        for mirror_description in entry.mirror_descriptions:
            lines.append(mirror_description)
        if entry.warning_text:
            lines.append(f"warning `{entry.warning_text}`")
        if display_index != len(page_entries):
            lines.append("")
        keyboard_rows.append(
            [
                {
                    "text": "↻",
                    "callback_data": _targeted_callback(
                        "refresh",
                        safe_page_index,
                        entry.chat_id,
                        entry.message_thread_id,
                    ),
                },
                {
                    "text": "➕",
                    "callback_data": _targeted_callback(
                        "new",
                        safe_page_index,
                        entry.chat_id,
                        entry.message_thread_id,
                    ),
                },
                {
                    "text": "✂",
                    "callback_data": _targeted_callback(
                        "unbind",
                        safe_page_index,
                        entry.chat_id,
                        entry.message_thread_id,
                    ),
                },
                {
                    "text": "📺",
                    "callback_data": _targeted_callback(
                        "live",
                        safe_page_index,
                        entry.chat_id,
                        entry.message_thread_id,
                    ),
                },
                {
                    "text": "📸",
                    "callback_data": _targeted_callback(
                        "screenshot",
                        safe_page_index,
                        entry.chat_id,
                        entry.message_thread_id,
                    ),
                },
                {
                    "text": "♻",
                    "callback_data": _targeted_callback(
                        "restore",
                        safe_page_index,
                        entry.chat_id,
                        entry.message_thread_id,
                    ),
                },
            ]
        )

    nav_row: list[dict[str, str]] = []
    if safe_page_index > 0:
        nav_row.append(
            {
                "text": "Prev",
                "callback_data": _global_callback("page", safe_page_index - 1),
            }
        )
    if safe_page_index + 1 < total_pages:
        nav_row.append(
            {
                "text": "Next",
                "callback_data": _global_callback("page", safe_page_index + 1),
            }
        )
    if nav_row:
        keyboard_rows.append(nav_row)
    if pending_jobs:
        lines.extend(
            [
                "",
                "Pending mirror topic creation",
                "",
                *pending_jobs,
            ]
        )
    keyboard_rows.append(
        [
            {"text": "Refresh", "callback_data": _global_callback("refresh", safe_page_index)},
            {"text": "Dismiss", "callback_data": f"{_SESSIONS_PREFIX}dismiss"},
        ]
    )
    return "\n".join(lines), {"inline_keyboard": keyboard_rows}


def render_unbind_confirmation(
    entry: SessionsDashboardEntry,
    *,
    page_index: int,
) -> tuple[str, dict[str, object]]:
    return (
        "Unbind this Telegram topic from Codex?\n\n"
        f"Topic title: `{entry.topic_name}`\n"
        f"Thread id: `{entry.codex_thread_id}`",
        {
            "inline_keyboard": [
                [
                    {
                        "text": "Confirm unbind",
                        "callback_data": _targeted_callback(
                            "unbind_confirm",
                            page_index,
                            entry.chat_id,
                            entry.message_thread_id,
                        ),
                    }
                ],
                [
                    {
                        "text": "Back",
                        "callback_data": _global_callback("unbind_cancel", page_index),
                    }
                ],
            ]
        },
    )


def parse_sessions_callback(data: str) -> dict[str, int | str | None] | None:
    if not data.startswith(_SESSIONS_PREFIX):
        return None
    payload = data[len(_SESSIONS_PREFIX) :]
    if payload == "dismiss":
        return {
            "action": "dismiss",
            "page_index": 0,
            "chat_id": None,
            "message_thread_id": None,
        }

    parts = payload.split(":")
    if len(parts) < 2:
        return None
    action = parts[0]
    if action not in _TARGETED_ACTIONS | _GLOBAL_ACTIONS:
        return None
    try:
        page_index = int(parts[1])
    except ValueError:
        return None

    if action in _TARGETED_ACTIONS and len(parts) == 4:
        try:
            return {
                "action": action,
                "page_index": page_index,
                "chat_id": int(parts[2]),
                "message_thread_id": int(parts[3]),
            }
        except ValueError:
            return None

    if action in _GLOBAL_ACTIONS and len(parts) == 2:
        return {
            "action": action,
            "page_index": page_index,
            "chat_id": None,
            "message_thread_id": None,
        }
    return None


def _global_callback(action: str, page_index: int) -> str:
    return f"{_SESSIONS_PREFIX}{action}:{page_index}"


def _targeted_callback(
    action: str,
    page_index: int,
    chat_id: int,
    message_thread_id: int,
) -> str:
    return f"{_SESSIONS_PREFIX}{action}:{page_index}:{chat_id}:{message_thread_id}"
