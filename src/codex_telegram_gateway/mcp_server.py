import argparse
import atexit
import threading
import traceback
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from mcp.server.fastmcp import FastMCP

from codex_telegram_gateway.commands_catalog import register_bot_commands_if_changed
from codex_telegram_gateway.codex_api import CodexAppServerClient, CodexAppServerError
from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.daemon import GatewayDaemon
from codex_telegram_gateway.service import GatewayService
from codex_telegram_gateway.state import SqliteGatewayState
from codex_telegram_gateway.sync_lock import SyncLock, try_acquire_sync_lock
from codex_telegram_gateway.telegram_api import TelegramApiError, TelegramBotClient

_DEFAULT_ENV_FILE = ".env"
_BACKGROUND_SYNC_INTERVAL_SECONDS = 2.0


@dataclass
class _Runtime:
    config: GatewayConfig
    state: SqliteGatewayState
    telegram: TelegramBotClient
    codex: CodexAppServerClient
    service: GatewayService
    daemon: GatewayDaemon


mcp = FastMCP(
    "Codex Telegram Gateway",
    instructions=(
        "Operate the Telegram gateway from inside Codex App context. "
        "Use loaded threads and loaded projects only."
    ),
)


@contextmanager
def _runtime(env_file: str | None) -> Iterator[_Runtime]:
    config = GatewayConfig.from_env(Path(_resolve_env_file(env_file)))
    state = SqliteGatewayState(config.state_database_path)
    telegram = TelegramBotClient(config.telegram_bot_token)
    with CodexAppServerClient(config) as codex:
        service = GatewayService(
            config=config,
            state=state,
            telegram=telegram,
            codex=codex,
        )
        daemon = GatewayDaemon(
            config=config,
            state=state,
            telegram=telegram,
            codex=codex,
        )
        yield _Runtime(
            config=config,
            state=state,
            telegram=telegram,
            codex=codex,
            service=service,
            daemon=daemon,
        )


def _resolve_env_file(env_file: str | None) -> str:
    return env_file or _DEFAULT_ENV_FILE


def auto_sync_loaded_threads(env_file: str | None = None) -> list[dict[str, object]]:
    """Create missing Telegram topics for all currently loaded Codex App threads."""
    with _runtime(env_file) as runtime:
        return [binding.__dict__ for binding in runtime.service.link_loaded_threads()]


def _background_sync_loop(stop_event: threading.Event, env_file: str) -> None:
    with _runtime(env_file) as runtime:
        _register_bot_commands(runtime)
        while not stop_event.is_set():
            try:
                runtime.daemon.poll_telegram_once()
                runtime.daemon.deliver_inbound_once()
                runtime.daemon.sync_codex_once()
                runtime.daemon.run_lifecycle_sweeps()
            except Exception:
                traceback.print_exc()
            stop_event.wait(_BACKGROUND_SYNC_INTERVAL_SECONDS)


def _start_background_sync(env_file: str) -> threading.Event | None:
    config = GatewayConfig.from_env(Path(_resolve_env_file(env_file)))
    sync_lock = try_acquire_sync_lock(config.sync_lock_path)
    if sync_lock is None:
        return None

    stop_event = threading.Event()
    worker = threading.Thread(
        target=_background_sync_loop,
        args=(stop_event, env_file),
        name="codex-telegram-background-sync",
        daemon=True,
    )
    worker.start()
    atexit.register(stop_event.set)
    atexit.register(_release_sync_lock, sync_lock)
    return stop_event


def _release_sync_lock(sync_lock: SyncLock) -> None:
    sync_lock.release()


def _register_bot_commands(runtime: _Runtime) -> None:
    try:
        register_bot_commands_if_changed(
            telegram=runtime.telegram,
            state=runtime.state,
            config=runtime.config,
        )
    except TelegramApiError:
        return


def _doctor_payload(runtime: _Runtime) -> dict[str, object]:
    chat = runtime.telegram.get_chat(runtime.config.telegram_default_chat_id)
    loaded_threads = runtime.codex.list_loaded_threads()
    loaded_projects = runtime.codex.list_loaded_projects()
    try:
        current_thread_id: str | None = runtime.codex.get_current_thread_id()
    except CodexAppServerError:
        current_thread_id = None
    return {
        "chat_id": runtime.config.telegram_default_chat_id,
        "chat_title": chat.get("title"),
        "chat_type": chat.get("type"),
        "current_thread_id": current_thread_id,
        "loaded_project_count": len(loaded_projects),
        "loaded_projects": [project.__dict__ for project in loaded_projects],
        "loaded_thread_count": len(loaded_threads),
        "loaded_threads": [thread.__dict__ for thread in loaded_threads],
    }


@mcp.tool(
    title="Gateway Doctor",
    description="Show Telegram connectivity plus the loaded Codex App projects and threads visible here.",
)
def doctor(env_file: str = ".env") -> dict[str, object]:
    with _runtime(env_file) as runtime:
        return _doctor_payload(runtime)


@mcp.tool(
    title="List Loaded Projects",
    description="List loaded Codex App projects, keyed by absolute folder path.",
)
def list_loaded_projects(env_file: str = ".env") -> list[dict[str, object]]:
    with _runtime(env_file) as runtime:
        return [project.__dict__ for project in runtime.codex.list_loaded_projects()]


@mcp.tool(
    title="List Loaded Threads",
    description="List loaded Codex App threads. This does not use historical CLI thread storage.",
)
def list_loaded_threads(env_file: str = ".env") -> list[dict[str, object]]:
    with _runtime(env_file) as runtime:
        return [thread.__dict__ for thread in runtime.codex.list_loaded_threads()]


@mcp.tool(
    title="List Gateway Bindings",
    description="Show persisted Codex thread to Telegram topic bindings from the local gateway database.",
)
def list_bindings(env_file: str = ".env") -> list[dict[str, object]]:
    with _runtime(env_file) as runtime:
        mirror_bindings_by_thread: dict[str, list[dict[str, object]]] = {}
        for mirror_binding in runtime.state.list_mirror_bindings():
            mirror_bindings_by_thread.setdefault(mirror_binding.codex_thread_id, []).append(
                mirror_binding.__dict__
            )
        return [
            {
                **binding.__dict__,
                "mirrors": mirror_bindings_by_thread.get(binding.codex_thread_id, []),
            }
            for binding in runtime.state.list_bindings()
        ]


@mcp.tool(
    title="Link Current Thread",
    description="Create or reuse the Telegram topic binding for the current Codex App thread.",
)
def link_current_thread(env_file: str = ".env") -> dict[str, object]:
    with _runtime(env_file) as runtime:
        return runtime.service.link_current_thread().__dict__


@mcp.tool(
    title="Link Loaded Threads",
    description="Create or reuse Telegram topics for all currently loaded Codex App threads.",
)
def link_loaded_threads(env_file: str = ".env") -> list[dict[str, object]]:
    with _runtime(env_file) as runtime:
        return [binding.__dict__ for binding in runtime.service.link_loaded_threads()]


@mcp.tool(
    title="Create Thread",
    description="Create a new Codex thread in the given project folder path.",
)
def create_thread(
    project_id: str,
    thread_name: str | None = None,
    env_file: str = ".env",
) -> dict[str, object]:
    with _runtime(env_file) as runtime:
        return runtime.codex.create_thread(project_id=project_id, thread_name=thread_name).__dict__


@mcp.tool(
    title="Sync Gateway Once",
    description="Run one Telegram poll, one inbound delivery, and one outbound Codex sync pass.",
)
def sync_once(env_file: str = ".env") -> dict[str, object]:
    with _runtime(env_file) as runtime:
        before = runtime.state.pending_inbound_count()
        runtime.daemon.poll_telegram_once()
        after_poll = runtime.state.pending_inbound_count()
        runtime.daemon.deliver_inbound_once()
        after_deliver = runtime.state.pending_inbound_count()
        runtime.daemon.sync_codex_once()
        runtime.daemon.run_lifecycle_sweeps()
        return {
            "pending_before": before,
            "pending_after_poll": after_poll,
            "pending_after_deliver": after_deliver,
        }


def main() -> None:
    global _DEFAULT_ENV_FILE

    parser = argparse.ArgumentParser(description="Codex Telegram gateway MCP server.")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the gateway .env file.",
    )
    args = parser.parse_args()
    _DEFAULT_ENV_FILE = args.env_file
    auto_sync_loaded_threads(_DEFAULT_ENV_FILE)
    _start_background_sync(_DEFAULT_ENV_FILE)
    mcp.run()


if __name__ == "__main__":
    main()
