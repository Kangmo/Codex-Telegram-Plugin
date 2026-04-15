"""Top-level topic recall prompt rendering."""

from __future__ import annotations

from codex_telegram_gateway.models import TopicHistoryEntry


INLINE_QUERY_MAX = 256
_LABEL_MAX = 48
_CALLBACK_DISMISS = "gw:recall:dismiss"


def history_entry_label(entry: TopicHistoryEntry, limit: int = 20) -> str:
    text_label = " ".join(entry.text.split()).strip()
    suffix = ""
    if entry.local_image_paths:
        image_count = len(entry.local_image_paths)
        label = "image" if image_count == 1 else "images"
        suffix = f"[{image_count} {label}]"
    if not text_label:
        label = suffix or "(empty message)"
        return label if len(label) <= limit else label[: limit - 1].rstrip() + "…"
    if not suffix:
        return text_label if len(text_label) <= limit else text_label[: limit - 1].rstrip() + "…"
    combined = f"{text_label} {suffix}"
    if len(combined) <= limit:
        return combined
    max_text_len = max(limit - len(suffix) - 2, 1)
    return f"{text_label[:max_text_len].rstrip()}… {suffix}"


def render_recall_prompt(entries: list[TopicHistoryEntry], *, limit: int = 10) -> tuple[str, dict[str, object]]:
    rows: list[list[dict[str, str]]] = []
    for index, entry in enumerate(entries[:limit]):
        button: dict[str, str] = {"text": f"↑ {history_entry_label(entry, limit=_LABEL_MAX)}"}
        if entry.local_image_paths:
            button["callback_data"] = f"gw:resp:recall:{index}"
        else:
            button["switch_inline_query_current_chat"] = entry.text[:INLINE_QUERY_MAX]
        rows.append([button])
    rows.append([{"text": "Close", "callback_data": _CALLBACK_DISMISS}])
    return (
        "Recent topic messages\n\n"
        "Tap a text-only entry to edit it inline before sending, or use the image entry buttons to replay the full message with attachments.",
        {"inline_keyboard": rows},
    )


def parse_recall_callback(data: str) -> str | None:
    if data == _CALLBACK_DISMISS:
        return "dismiss"
    return None
