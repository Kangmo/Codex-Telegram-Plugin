from codex_telegram_gateway.models import TopicLifecycle
from codex_telegram_gateway.topic_lifecycle import (
    is_unbound_topic_expired,
    should_autoclose_topic,
    should_probe_topics,
    should_prune_state,
)


def test_should_probe_topics_respects_interval() -> None:
    assert should_probe_topics(10.0, now=70.0, interval_seconds=60.0) is True
    assert should_probe_topics(10.0, now=69.9, interval_seconds=60.0) is False


def test_should_prune_state_respects_interval() -> None:
    assert should_prune_state(10.0, now=310.0, interval_seconds=300.0) is True
    assert should_prune_state(10.0, now=309.9, interval_seconds=300.0) is False


def test_should_autoclose_topic_requires_completed_at_and_timeout() -> None:
    completed = TopicLifecycle(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
        completed_at=10.0,
    )
    incomplete = TopicLifecycle(
        codex_thread_id="thread-1",
        chat_id=-100100,
        message_thread_id=77,
    )

    assert should_autoclose_topic(completed, now=50.0, timeout_seconds=30.0) is True
    assert should_autoclose_topic(completed, now=39.9, timeout_seconds=30.0) is False
    assert should_autoclose_topic(completed, now=50.0, timeout_seconds=0.0) is False
    assert should_autoclose_topic(incomplete, now=50.0, timeout_seconds=30.0) is False


def test_is_unbound_topic_expired_requires_last_seen_and_positive_ttl() -> None:
    assert is_unbound_topic_expired(10.0, now=50.0, ttl_seconds=30.0) is True
    assert is_unbound_topic_expired(10.0, now=39.9, ttl_seconds=30.0) is False
    assert is_unbound_topic_expired(None, now=50.0, ttl_seconds=30.0) is False
    assert is_unbound_topic_expired(10.0, now=50.0, ttl_seconds=0.0) is False
