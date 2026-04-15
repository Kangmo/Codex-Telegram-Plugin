from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from codex_telegram_gateway.models import CodexHistoryEntry


CALLBACK_HISTORY_PREFIX = "gw:hist:"


@dataclass(frozen=True)
class RenderedHistoryPage:
    """A paginated Telegram rendering of one Codex thread history page."""

    text: str
    reply_markup: dict[str, object] | None
    page_index: int
    total_pages: int


def parse_history_callback(data: str) -> tuple[int, str] | None:
    """Parse `gw:hist:<page>:<thread_id>` callback payloads."""

    if not data.startswith(CALLBACK_HISTORY_PREFIX):
        return None
    payload = data[len(CALLBACK_HISTORY_PREFIX):]
    page_index_text, separator, thread_id = payload.partition(":")
    if separator == "" or not thread_id:
        return None
    try:
        page_index = int(page_index_text)
    except ValueError:
        return None
    return (page_index, thread_id)


def render_history_page(
    *,
    display_name: str,
    thread_id: str,
    entries: list[CodexHistoryEntry],
    page_index: int = -1,
) -> RenderedHistoryPage:
    """Render a history page with ccgram-style older/newer pagination."""

    if not entries:
        return RenderedHistoryPage(
            text=f"📋 [{display_name}] No messages yet.",
            reply_markup=None,
            page_index=0,
            total_pages=1,
        )

    header = f"📋 [{display_name}] Messages ({len(entries)} total)"
    entry_blocks: list[str] = []
    for entry in entries:
        timestamp = _format_timestamp(entry.timestamp)
        separator = f"───── {timestamp} ─────" if timestamp else "─────────────"
        entry_blocks.append(f"{separator}\n\n{_history_entry_text(entry)}")

    pages = [
        f"{header}\n\n{page_body}".rstrip()
        for page_body in _split_pages("\n\n".join(entry_blocks), max_length=3200)
    ]
    normalized_page_index = len(pages) - 1 if page_index < 0 else max(0, min(page_index, len(pages) - 1))
    return RenderedHistoryPage(
        text=pages[normalized_page_index],
        reply_markup=_history_markup(
            thread_id=thread_id,
            page_index=normalized_page_index,
            total_pages=len(pages),
        ),
        page_index=normalized_page_index,
        total_pages=len(pages),
    )


def _history_markup(
    *,
    thread_id: str,
    page_index: int,
    total_pages: int,
) -> dict[str, object] | None:
    if total_pages <= 1:
        return None

    row: list[dict[str, str]] = []
    if page_index > 0:
        row.append(
            {
                "text": "◀ Older",
                "callback_data": f"{CALLBACK_HISTORY_PREFIX}{page_index - 1}:{thread_id}",
            }
        )
    row.append({"text": f"{page_index + 1}/{total_pages}", "callback_data": "tp:noop"})
    if page_index < total_pages - 1:
        row.append(
            {
                "text": "Newer ▶",
                "callback_data": f"{CALLBACK_HISTORY_PREFIX}{page_index + 1}:{thread_id}",
            }
        )
    return {"inline_keyboard": [row]}


def _format_timestamp(timestamp: str | None) -> str:
    if not timestamp:
        return ""
    normalized = timestamp.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized).strftime("%H:%M")
    except ValueError:
        return ""


def _history_entry_text(entry: CodexHistoryEntry) -> str:
    if entry.kind == "user":
        return f"👤 {entry.text}"
    if entry.kind == "tool":
        return f"🛠 {entry.text}"
    if entry.kind == "thinking":
        return f"🧠 {entry.text}"
    return f"🤖 {entry.text}"


def _split_pages(text: str, max_length: int = 3500) -> list[str]:
    if len(text) <= max_length:
        return [text]

    pages: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= max_length:
            pages.append(remaining)
            break
        split_at = remaining.rfind("\n\n", 0, max_length)
        if split_at <= 0:
            split_at = remaining.rfind("\n", 0, max_length)
        if split_at <= 0:
            split_at = max_length
        pages.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return pages
