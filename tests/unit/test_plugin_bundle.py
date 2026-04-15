import importlib
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

from codex_telegram_gateway.models import Binding


def test_plugin_manifest_points_to_plugin_local_mcp_server() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    plugin_manifest = json.loads((repo_root / ".codex-plugin" / "plugin.json").read_text())
    mcp_manifest = json.loads((repo_root / ".mcp.json").read_text())

    assert plugin_manifest["mcpServers"] == "./.mcp.json"
    server = mcp_manifest["mcpServers"]["codex-telegram-gateway"]
    assert server["command"] == "./.venv/bin/python"
    assert server["args"] == ["-m", "codex_telegram_gateway.mcp_server", "--env-file", ".env"]


def test_mcp_server_module_imports() -> None:
    module = importlib.import_module("codex_telegram_gateway.mcp_server")

    assert hasattr(module, "mcp")


def test_auto_sync_loaded_threads_calls_service(monkeypatch) -> None:
    module = importlib.import_module("codex_telegram_gateway.mcp_server")
    calls: list[str | None] = []

    class FakeService:
        def link_loaded_threads(self) -> list[Binding]:
            calls.append("called")
            return [
                Binding(
                    codex_thread_id="thread-1",
                    chat_id=-100,
                    message_thread_id=7,
                    topic_name="(blink) Remove browser entitlement",
                    sync_mode="assistant_plus_alerts",
                    project_id="/Users/kangmo/projs/blink",
                )
            ]

    @contextmanager
    def fake_runtime(env_file: str | None):
        calls.append(env_file)
        yield SimpleNamespace(service=FakeService())

    monkeypatch.setattr(module, "_runtime", fake_runtime)

    result = module.auto_sync_loaded_threads("test.env")

    assert calls == ["test.env", "called"]
    assert result == [
        {
            "codex_thread_id": "thread-1",
            "chat_id": -100,
            "message_thread_id": 7,
            "topic_name": "(blink) Remove browser entitlement",
            "sync_mode": "assistant_plus_alerts",
            "project_id": "/Users/kangmo/projs/blink",
            "binding_status": "active",
        }
    ]


def test_sync_once_runs_lifecycle_sweeps(monkeypatch) -> None:
    module = importlib.import_module("codex_telegram_gateway.mcp_server")
    calls: list[str] = []

    class FakeState:
        def __init__(self) -> None:
            self._counts = iter([2, 3, 1])

        def pending_inbound_count(self) -> int:
            return next(self._counts)

    class FakeDaemon:
        def poll_telegram_once(self) -> None:
            calls.append("poll_telegram_once")

        def deliver_inbound_once(self) -> None:
            calls.append("deliver_inbound_once")

        def sync_codex_once(self) -> None:
            calls.append("sync_codex_once")

        def run_lifecycle_sweeps(self) -> None:
            calls.append("run_lifecycle_sweeps")

    @contextmanager
    def fake_runtime(env_file: str | None):
        calls.append(f"runtime:{env_file}")
        yield SimpleNamespace(
            state=FakeState(),
            daemon=FakeDaemon(),
        )

    monkeypatch.setattr(module, "_runtime", fake_runtime)

    result = module.sync_once("test.env")

    assert calls == [
        "runtime:test.env",
        "poll_telegram_once",
        "deliver_inbound_once",
        "sync_codex_once",
        "run_lifecycle_sweeps",
    ]
    assert result == {
        "pending_before": 2,
        "pending_after_poll": 3,
        "pending_after_deliver": 1,
    }


def test_list_bindings_includes_mirrors(monkeypatch) -> None:
    module = importlib.import_module("codex_telegram_gateway.mcp_server")

    @contextmanager
    def fake_runtime(env_file: str | None):
        del env_file
        yield SimpleNamespace(
            state=SimpleNamespace(
                list_bindings=lambda: [
                    Binding(
                        codex_thread_id="thread-1",
                        chat_id=-100100,
                        message_thread_id=7,
                        topic_name="(blink) Remove browser entitlement",
                        sync_mode="assistant_plus_alerts",
                        project_id="/Users/kangmo/projs/blink",
                    )
                ],
                list_mirror_bindings=lambda: [
                    Binding(
                        codex_thread_id="thread-1",
                        chat_id=-100200,
                        message_thread_id=8,
                        topic_name="(blink) Remove browser entitlement",
                        sync_mode="assistant_plus_alerts",
                        project_id="/Users/kangmo/projs/blink",
                    )
                ],
            )
        )

    monkeypatch.setattr(module, "_runtime", fake_runtime)

    result = module.list_bindings("test.env")

    assert result == [
        {
            "codex_thread_id": "thread-1",
            "chat_id": -100100,
            "message_thread_id": 7,
            "topic_name": "(blink) Remove browser entitlement",
            "sync_mode": "assistant_plus_alerts",
            "project_id": "/Users/kangmo/projs/blink",
            "binding_status": "active",
            "mirrors": [
                {
                    "codex_thread_id": "thread-1",
                    "chat_id": -100200,
                    "message_thread_id": 8,
                    "topic_name": "(blink) Remove browser entitlement",
                    "sync_mode": "assistant_plus_alerts",
                    "project_id": "/Users/kangmo/projs/blink",
                    "binding_status": "active",
                }
            ],
        }
    ]
