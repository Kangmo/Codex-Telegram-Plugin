from codex_telegram_gateway.topic_status import (
    TOPIC_STATUS_APPROVAL,
    TOPIC_STATUS_CLOSED,
    TOPIC_STATUS_FAILED,
    TOPIC_STATUS_IDLE,
    TOPIC_STATUS_RUNNING,
    format_topic_title_for_status,
    strip_topic_status_prefix,
)


def test_format_topic_title_for_status_adds_prefix_only_for_non_idle_statuses() -> None:
    assert format_topic_title_for_status(
        "(blink) Run tests",
        TOPIC_STATUS_IDLE,
        emoji_enabled=True,
    ) == "(blink) Run tests"
    assert format_topic_title_for_status(
        "(blink) Run tests",
        TOPIC_STATUS_RUNNING,
        emoji_enabled=True,
    ) == "🟢 (blink) Run tests"
    assert format_topic_title_for_status(
        "(blink) Run tests",
        TOPIC_STATUS_APPROVAL,
        emoji_enabled=True,
    ) == "🟠 (blink) Run tests"
    assert format_topic_title_for_status(
        "(blink) Run tests",
        TOPIC_STATUS_FAILED,
        emoji_enabled=True,
    ) == "💥 (blink) Run tests"
    assert format_topic_title_for_status(
        "(blink) Run tests",
        TOPIC_STATUS_CLOSED,
        emoji_enabled=True,
    ) == "⚫ (blink) Run tests"


def test_format_topic_title_for_status_can_disable_emoji_prefixes() -> None:
    assert format_topic_title_for_status(
        "🟢 (blink) Run tests",
        TOPIC_STATUS_RUNNING,
        emoji_enabled=False,
    ) == "(blink) Run tests"


def test_strip_topic_status_prefix_removes_known_gateway_prefixes() -> None:
    assert strip_topic_status_prefix("🟢 (blink) Run tests") == "(blink) Run tests"
    assert strip_topic_status_prefix("🟠 (blink) Run tests") == "(blink) Run tests"
    assert strip_topic_status_prefix("💥 (blink) Run tests") == "(blink) Run tests"
    assert strip_topic_status_prefix("⚫ (blink) Run tests") == "(blink) Run tests"
    assert strip_topic_status_prefix("(blink) Run tests") == "(blink) Run tests"
