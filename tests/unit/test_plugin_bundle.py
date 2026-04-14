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
        }
    ]
