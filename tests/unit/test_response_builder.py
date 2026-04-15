from codex_telegram_gateway.models import CodexEvent
from codex_telegram_gateway.response_builder import build_outbound_events


def test_build_outbound_events_batches_adjacent_commands_into_one_tool_event() -> None:
    turns = [
        {
            "id": "turn-1",
            "status": "in_progress",
            "items": [
                {
                    "id": "cmd-1",
                    "type": "commandExecution",
                    "command": "pwd",
                    "exitCode": 0,
                    "aggregatedOutput": "/tmp/project",
                },
                {
                    "id": "cmd-2",
                    "type": "commandExecution",
                    "command": "pytest -q",
                },
            ],
        }
    ]

    assert build_outbound_events("thread-1", turns) == [
        CodexEvent(
            event_id="thread-1:turn-1:tool-batch:0",
            thread_id="thread-1",
            kind="tool_batch",
            text="⚡ 2 commands\n• pwd  ✅ /tmp/project\n• pytest -q  ⏳ running",
        )
    ]


def test_build_outbound_events_adds_terminal_summary_when_turn_has_no_assistant_reply() -> None:
    turns = [
        {
            "id": "turn-1",
            "status": "failed",
            "items": [
                {
                    "id": "cmd-1",
                    "type": "commandExecution",
                    "command": "pytest -q",
                    "exitCode": 1,
                    "aggregatedOutput": "tests failed\nAssertionError: boom",
                }
            ],
        }
    ]

    assert build_outbound_events("thread-1", turns) == [
        CodexEvent(
            event_id="thread-1:turn-1:tool-batch:0",
            thread_id="thread-1",
            kind="tool_batch",
            text="⚡ 1 command\n• pytest -q  ❌ AssertionError: boom",
        ),
        CodexEvent(
            event_id="thread-1:turn-1:completion-summary",
            thread_id="thread-1",
            kind="completion_summary",
            text="⚠ Turn failed — pytest -q: AssertionError: boom",
        ),
    ]


def test_build_outbound_events_skips_completion_summary_when_final_assistant_message_exists() -> None:
    turns = [
        {
            "id": "turn-1",
            "status": "completed",
            "items": [
                {
                    "id": "cmd-1",
                    "type": "commandExecution",
                    "command": "pytest -q",
                    "exitCode": 0,
                    "aggregatedOutput": "3 passed in 0.80s",
                },
                {
                    "id": "item-2",
                    "type": "agentMessage",
                    "phase": "final",
                    "text": "All tests are green now.",
                },
            ],
        }
    ]

    assert build_outbound_events("thread-1", turns) == [
        CodexEvent(
            event_id="thread-1:turn-1:tool-batch:0",
            thread_id="thread-1",
            kind="tool_batch",
            text="⚡ 1 command\n• pytest -q  ✅ 3 passed in 0.80s",
        ),
        CodexEvent(
            event_id="thread-1:turn-1:item-2",
            thread_id="thread-1",
            kind="assistant_message",
            text="All tests are green now.",
        ),
    ]


def test_build_outbound_events_keeps_terminal_summary_when_commands_are_last() -> None:
    turns = [
        {
            "id": "turn-1",
            "status": "completed",
            "items": [
                {
                    "id": "item-1",
                    "type": "agentMessage",
                    "phase": "final",
                    "text": "I am checking the current test state.",
                },
                {
                    "id": "cmd-1",
                    "type": "commandExecution",
                    "command": "pytest -q",
                    "exitCode": 0,
                    "aggregatedOutput": "3 passed in 0.80s",
                },
            ],
        }
    ]

    assert build_outbound_events("thread-1", turns) == [
        CodexEvent(
            event_id="thread-1:turn-1:item-1",
            thread_id="thread-1",
            kind="assistant_message",
            text="I am checking the current test state.",
        ),
        CodexEvent(
            event_id="thread-1:turn-1:tool-batch:0",
            thread_id="thread-1",
            kind="tool_batch",
            text="⚡ 1 command\n• pytest -q  ✅ 3 passed in 0.80s",
        ),
        CodexEvent(
            event_id="thread-1:turn-1:completion-summary",
            thread_id="thread-1",
            kind="completion_summary",
            text="✓ Done — pytest -q: 3 passed in 0.80s",
        ),
    ]
