import json
import sqlite3
from unittest.mock import patch

from codex_telegram_gateway.codex_api import CodexAppServerClient, _build_turn_input, _turn_waits_for_approval
from codex_telegram_gateway.models import CodexHistoryEntry, CodexThread
from codex_telegram_gateway.models import StartedTurn


def test_build_turn_input_uses_local_image_variant_expected_by_app_server() -> None:
    started_turn = StartedTurn(
        thread_id="thread-1",
        text="Inspect the attachment.",
        local_image_paths=("/tmp/example.png",),
    )

    assert _build_turn_input(started_turn) == [
        {"type": "localImage", "path": "/tmp/example.png"},
        {"type": "text", "text": "Inspect the attachment."},
    ]


def test_turn_waits_for_approval_when_rollout_requests_escalation(tmp_path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    database_path = codex_home / "state_5.sqlite"
    rollout_path = codex_home / "sessions" / "rollout-thread-1.jsonl"
    rollout_path.parent.mkdir(parents=True)

    connection = sqlite3.connect(database_path)
    try:
        connection.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                rollout_path TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO threads (id, rollout_path) VALUES (?, ?)",
            ("thread-1", str(rollout_path)),
        )
        connection.commit()
    finally:
        connection.close()

    rollout_path.write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "type": "event_msg",
                        "payload": {
                            "type": "task_started",
                            "turn_id": "turn-1",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "turn_context",
                        "payload": {
                            "turn_id": "turn-1",
                            "approval_policy": "on-request",
                        },
                    }
                ),
                json.dumps(
                    {
                        "type": "response_item",
                        "payload": {
                            "type": "function_call",
                            "arguments": json.dumps(
                                {
                                    "cmd": "mysql -h127.0.0.1 -P13307 -uroot",
                                    "sandbox_permissions": "require_escalated",
                                }
                            ),
                        },
                    }
                ),
            ]
        )
    )

    assert _turn_waits_for_approval(codex_home, "thread-1", "turn-1") is True


def test_list_loaded_threads_uses_app_loaded_list_api_and_deduplicates() -> None:
    client = CodexAppServerClient.__new__(CodexAppServerClient)
    requests: list[tuple[str, dict[str, object]]] = []

    def fake_request(method: str, params: dict[str, object]) -> dict[str, object]:
        requests.append((method, params))
        if params["cursor"] is None:
            return {"data": ["thread-1", "thread-2"], "nextCursor": "cursor-2"}
        return {"data": ["thread-2", "thread-3"]}

    def fake_read_thread(thread_id: str) -> CodexThread:
        return CodexThread(thread_id=thread_id, title=thread_id, status="idle", cwd=f"/tmp/{thread_id}")

    client._request = fake_request  # type: ignore[attr-defined]
    client.read_thread = fake_read_thread  # type: ignore[method-assign]

    threads = client.list_loaded_threads()

    assert [thread.thread_id for thread in threads] == ["thread-1", "thread-2", "thread-3"]
    assert requests == [
        ("thread/loaded/list", {"cursor": None, "limit": 100}),
        ("thread/loaded/list", {"cursor": "cursor-2", "limit": 100}),
    ]


def test_steer_turn_uses_active_turn_rpc_with_expected_turn_id() -> None:
    client = CodexAppServerClient.__new__(CodexAppServerClient)
    requests: list[tuple[str, dict[str, object]]] = []

    def fake_request(method: str, params: dict[str, object]) -> dict[str, object]:
        requests.append((method, params))
        return {"turnId": "turn-1"}

    client._request = fake_request  # type: ignore[attr-defined]

    result = client.steer_turn(
        StartedTurn(
            thread_id="thread-1",
            text="Please continue with more detail.",
            local_image_paths=("/tmp/example.png",),
        ),
        expected_turn_id="turn-1",
    )

    assert result == __import__("codex_telegram_gateway.models", fromlist=["TurnResult"]).TurnResult(
        turn_id="turn-1",
        status="in_progress",
    )
    assert requests == [
        (
            "turn/steer",
            {
                "threadId": "thread-1",
                "expectedTurnId": "turn-1",
                "input": [
                    {"type": "localImage", "path": "/tmp/example.png"},
                    {"type": "text", "text": "Please continue with more detail."},
                ],
            },
        )
    ]


def test_rename_thread_uses_thread_name_set_rpc() -> None:
    client = CodexAppServerClient.__new__(CodexAppServerClient)
    requests: list[tuple[str, dict[str, object]]] = []

    def fake_request(method: str, params: dict[str, object]) -> dict[str, object]:
        requests.append((method, params))
        return {}

    def fake_read_thread(thread_id: str) -> CodexThread:
        return CodexThread(
            thread_id=thread_id,
            title="renamed thread",
            status="idle",
            cwd="/tmp/project",
        )

    client._request = fake_request  # type: ignore[attr-defined]
    client.read_thread = fake_read_thread  # type: ignore[method-assign]

    renamed = client.rename_thread("thread-1", "renamed thread")

    assert renamed == CodexThread(
        thread_id="thread-1",
        title="renamed thread",
        status="idle",
        cwd="/tmp/project",
    )
    assert requests == [
        (
            "thread/name/set",
            {
                "threadId": "thread-1",
                "name": "renamed thread",
            },
        )
    ]


def test_list_history_entries_normalizes_user_assistant_and_command_items() -> None:
    client = CodexAppServerClient.__new__(CodexAppServerClient)

    def fake_request(method: str, params: dict[str, object]) -> dict[str, object]:
        assert method == "thread/read"
        assert params == {"threadId": "thread-1", "includeTurns": True}
        return {
            "thread": {
                "turns": [
                    {
                        "id": "turn-1",
                        "startedAt": "2026-04-15T10:00:00Z",
                        "completedAt": "2026-04-15T10:01:00Z",
                        "items": [
                            {
                                "id": "item-1",
                                "type": "userMessage",
                                "content": [
                                    {"type": "text", "text": "Please review this screenshot."},
                                    {"type": "localImage", "path": "/tmp/example.png"},
                                ],
                            },
                            {
                                "id": "item-2",
                                "type": "agentMessage",
                                "phase": "commentary",
                                "text": "I am still thinking.",
                            },
                            {
                                "id": "item-3",
                                "type": "commandExecution",
                                "command": "pytest -q",
                                "exitCode": 1,
                                "durationMs": 45,
                                "aggregatedOutput": "tests failed\nAssertionError: boom",
                            },
                            {
                                "id": "item-4",
                                "type": "agentMessage",
                                "phase": "final",
                                "text": "The failing test comes from the assertion mismatch.",
                            },
                        ],
                    }
                ]
            }
        }

    client._request = fake_request  # type: ignore[attr-defined]

    assert client.list_history_entries("thread-1") == [
        CodexHistoryEntry(
            entry_id="thread-1:turn-1:item-1",
            kind="user",
            text="Please review this screenshot.\n[1 image attached]",
            timestamp="2026-04-15T10:00:00Z",
        ),
        CodexHistoryEntry(
            entry_id="thread-1:turn-1:item-3",
            kind="tool",
            text="pytest -q | exit 1 • 45ms\nAssertionError: boom",
            timestamp="2026-04-15T10:01:00Z",
        ),
        CodexHistoryEntry(
            entry_id="thread-1:turn-1:item-4",
            kind="assistant",
            text="The failing test comes from the assertion mismatch.",
            timestamp="2026-04-15T10:01:00Z",
        ),
    ]


def test_list_resumable_threads_uses_app_store_threads_and_marks_unloaded() -> None:
    client = CodexAppServerClient.__new__(CodexAppServerClient)
    client._codex_home = __import__("pathlib").Path("/tmp/.codex")  # type: ignore[attr-defined]

    def fake_list_loaded_threads() -> list[CodexThread]:
        return [
            CodexThread(
                thread_id="thread-2",
                title="Loaded thread",
                status="idle",
                cwd="/tmp/project",
            )
        ]

    client.list_loaded_threads = fake_list_loaded_threads  # type: ignore[method-assign]

    with patch("codex_telegram_gateway.codex_api.list_project_threads") as list_project_threads:
        list_project_threads.return_value = [
            __import__("codex_telegram_gateway.app_store", fromlist=["AppStoreThread"]).AppStoreThread(
                thread_id="thread-2",
                cwd="/tmp/project",
                title="Loaded thread",
                updated_at=20,
            ),
            __import__("codex_telegram_gateway.app_store", fromlist=["AppStoreThread"]).AppStoreThread(
                thread_id="thread-3",
                cwd="/tmp/project",
                title="Older thread",
                updated_at=10,
            ),
        ]

        assert client.list_resumable_threads("/tmp/project", exclude_thread_id="thread-1") == [
            CodexThread(
                thread_id="thread-2",
                title="Loaded thread",
                status="idle",
                cwd="/tmp/project",
            ),
            CodexThread(
                thread_id="thread-3",
                title="Older thread",
                status="notLoaded",
                cwd="/tmp/project",
            ),
        ]
        list_project_threads.assert_called_once_with(
            client._codex_home,  # type: ignore[attr-defined]
            "/tmp/project",
            exclude_thread_id="thread-1",
            limit=12,
        )
