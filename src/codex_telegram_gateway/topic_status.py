"""Helpers for lightweight topic lifecycle status in Telegram titles."""

TOPIC_STATUS_IDLE = "idle"
TOPIC_STATUS_RUNNING = "running"
TOPIC_STATUS_APPROVAL = "approval"
TOPIC_STATUS_FAILED = "failed"
TOPIC_STATUS_CLOSED = "closed"

_STATUS_EMOJI_BY_NAME = {
    TOPIC_STATUS_IDLE: "",
    TOPIC_STATUS_RUNNING: "🟢",
    TOPIC_STATUS_APPROVAL: "🟠",
    TOPIC_STATUS_FAILED: "💥",
    TOPIC_STATUS_CLOSED: "⚫",
}

_STATUS_PREFIXES = tuple(
    f"{emoji} "
    for emoji in _STATUS_EMOJI_BY_NAME.values()
    if emoji
)


def format_topic_title_for_status(
    base_title: str,
    status: str,
    *,
    emoji_enabled: bool,
) -> str:
    clean_title = strip_topic_status_prefix(base_title)
    if not emoji_enabled:
        return clean_title
    emoji = _STATUS_EMOJI_BY_NAME.get(status, "")
    if not emoji:
        return clean_title
    return f"{emoji} {clean_title}"


def strip_topic_status_prefix(topic_title: str) -> str:
    stripped = topic_title.strip()
    for prefix in _STATUS_PREFIXES:
        if stripped.startswith(prefix):
            return stripped[len(prefix) :].strip()
    return stripped
