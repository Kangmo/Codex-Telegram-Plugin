"""Pure lifecycle helpers for periodic topic hygiene."""

from codex_telegram_gateway.models import TopicLifecycle


def should_probe_topics(last_probe_started_at: float, *, now: float, interval_seconds: float) -> bool:
    return now - last_probe_started_at >= interval_seconds


def should_prune_state(last_prune_started_at: float, *, now: float, interval_seconds: float) -> bool:
    return now - last_prune_started_at >= interval_seconds


def should_autoclose_topic(
    topic_lifecycle: TopicLifecycle,
    *,
    now: float,
    timeout_seconds: float,
) -> bool:
    if timeout_seconds <= 0:
        return False
    if topic_lifecycle.completed_at is None:
        return False
    return now - topic_lifecycle.completed_at >= timeout_seconds


def is_unbound_topic_expired(last_seen_at: float | None, *, now: float, ttl_seconds: float) -> bool:
    if last_seen_at is None or ttl_seconds <= 0:
        return False
    return now - last_seen_at >= ttl_seconds
