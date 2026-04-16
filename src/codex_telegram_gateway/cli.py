import argparse
import getpass
import json
import sys
import threading
import time
from pathlib import Path

from codex_telegram_gateway.commands_catalog import register_bot_commands_if_changed
from codex_telegram_gateway.codex_api import CodexAppServerClient, CodexAppServerError
from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.daemon import GatewayDaemon
from codex_telegram_gateway.install_config import (
    build_managed_env,
    load_existing_env,
    prompt_install_answers,
    write_env_file,
)
from codex_telegram_gateway.runtime_paths import ensure_runtime_directories, resolve_runtime_paths
from codex_telegram_gateway.service import GatewayService
from codex_telegram_gateway.state import SqliteGatewayState
from codex_telegram_gateway.sync_lock import try_acquire_sync_lock
from codex_telegram_gateway.telegram_api import TelegramApiError, TelegramBotClient


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Codex Telegram gateway utility.")
    parser.add_argument(
        "--env-file",
        default=".env",
        help="Path to the env file that holds Telegram credentials.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("doctor", help="Validate Telegram and Codex connectivity.")
    subparsers.add_parser(
        "link-loaded-threads",
        help="Create Telegram topics for all currently loaded Codex threads.",
    )
    subparsers.add_parser(
        "link-workspace-threads",
        help=argparse.SUPPRESS,
    )
    subparsers.add_parser(
        "link-all-threads",
        help=argparse.SUPPRESS,
    )
    install_parser = subparsers.add_parser(
        "install",
        help="Interactively configure the managed gateway runtime.",
    )
    install_parser.add_argument(
        "--group-chat-id",
        type=int,
        default=None,
        help="Override the prompted Telegram group chat ID.",
    )
    configure_parser = subparsers.add_parser(
        "configure",
        help="Update the managed gateway runtime configuration.",
    )
    configure_parser.add_argument(
        "--group-chat-id",
        type=int,
        default=None,
        help="Override the prompted Telegram group chat ID.",
    )
    subparsers.add_parser(
        "sync-once",
        help="Run one Telegram poll, one inbound delivery, and one outbound Codex sync pass.",
    )
    run_daemon_parser = subparsers.add_parser(
        "run-daemon",
        help="Run the Telegram gateway loop continuously.",
    )
    run_daemon_parser.add_argument(
        "--interval-seconds",
        type=float,
        default=2.0,
        help="Seconds to sleep between gateway loop iterations.",
    )
    subparsers.add_parser(
        "link-current-thread",
        help="Create a Telegram topic for the current Codex thread.",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "install":
            _run_install_or_configure(group_chat_id_override=args.group_chat_id, is_install=True)
            return
        if args.command == "configure":
            _run_install_or_configure(group_chat_id_override=args.group_chat_id, is_install=False)
            return
        config = GatewayConfig.from_env(Path(args.env_file))
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

            if args.command == "doctor":
                _run_doctor(config, telegram, codex)
                return
            if args.command == "sync-once":
                print(json.dumps(_run_sync_iteration(state, service, daemon), indent=2, sort_keys=True))
                return
            if args.command == "run-daemon":
                _register_bot_commands(telegram=telegram, state=state, config=config)
                sync_lock = try_acquire_sync_lock(config.sync_lock_path)
                if sync_lock is None:
                    raise ValueError(
                        f"Another Telegram background sync is already running: {config.sync_lock_path}"
                    )
                stop_event = threading.Event()
                poll_thread = threading.Thread(
                    target=_run_poll_loop,
                    args=(config, args.interval_seconds, stop_event),
                    daemon=True,
                    name="codex-telegram-poll-loop",
                )
                poll_thread.start()
                try:
                    _run_codex_loop(config, args.interval_seconds, stop_event)
                except KeyboardInterrupt:
                    stop_event.set()
                    sync_lock.release()
                    return
                sync_lock.release()
                return
            if args.command == "link-current-thread":
                binding = service.link_current_thread()
                print(json.dumps(binding.__dict__, indent=2, sort_keys=True))
                return
            if args.command == "link-loaded-threads":
                bindings = service.link_loaded_threads()
                print(
                    json.dumps([binding.__dict__ for binding in bindings], indent=2, sort_keys=True)
                )
                return
            if args.command == "link-workspace-threads":
                raise ValueError(
                    "Workspace history discovery is disabled. Use link-loaded-threads "
                    "from the Codex app context."
                )
            if args.command == "link-all-threads":
                raise ValueError(
                    "Historical thread/list discovery is disabled. Use link-loaded-threads "
                    "or link-current-thread from the Codex app context."
                )
            raise ValueError(f"Unsupported command: {args.command}")
    except (CodexAppServerError, TelegramApiError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc


def _run_doctor(
    config: GatewayConfig,
    telegram: TelegramBotClient,
    codex: CodexAppServerClient,
) -> None:
    chat = telegram.get_chat(config.telegram_default_chat_id)
    threads = codex.list_loaded_threads()
    try:
        current_thread_id: str | None = codex.get_current_thread_id()
    except CodexAppServerError:
        current_thread_id = None
    payload = {
        "chat_id": config.telegram_default_chat_id,
        "chat_title": chat.get("title"),
        "chat_type": chat.get("type"),
        "current_thread_id": current_thread_id,
        "loaded_project_count": len(codex.list_loaded_projects()),
        "loaded_projects": [project.__dict__ for project in codex.list_loaded_projects()],
        "loaded_thread_count": len(threads),
        "loaded_threads": [thread.__dict__ for thread in threads],
    }
    print(json.dumps(payload, indent=2, sort_keys=True))


def _run_sync_iteration(
    state: SqliteGatewayState,
    service: GatewayService,
    daemon: GatewayDaemon,
) -> dict[str, int]:
    service.link_loaded_threads()
    before = state.pending_inbound_count()
    daemon.poll_telegram_once()
    after_poll = state.pending_inbound_count()
    daemon.deliver_inbound_once()
    after_deliver = state.pending_inbound_count()
    daemon.sync_codex_once()
    daemon.run_lifecycle_sweeps()
    return {
        "pending_before": before,
        "pending_after_poll": after_poll,
        "pending_after_deliver": after_deliver,
    }


def _run_poll_loop(
    config: GatewayConfig,
    interval_seconds: float,
    stop_event: threading.Event,
) -> None:
    state = SqliteGatewayState(config.state_database_path)
    telegram = TelegramBotClient(config.telegram_bot_token)
    with CodexAppServerClient(config) as codex:
        daemon = GatewayDaemon(
            config=config,
            state=state,
            telegram=telegram,
            codex=codex,
        )
        while not stop_event.is_set():
            try:
                daemon.poll_telegram_once()
                daemon.run_lifecycle_sweeps()
            except Exception as exc:
                print(str(exc), file=sys.stderr)
            stop_event.wait(interval_seconds)


def _run_codex_loop(
    config: GatewayConfig,
    interval_seconds: float,
    stop_event: threading.Event,
) -> None:
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
        while not stop_event.is_set():
            try:
                service.link_loaded_threads()
                daemon.deliver_inbound_once()
                daemon.sync_codex_once()
                daemon.run_lifecycle_sweeps()
            except Exception as exc:
                print(str(exc), file=sys.stderr)
            stop_event.wait(interval_seconds)


def _register_bot_commands(
    *,
    telegram: TelegramBotClient,
    state: SqliteGatewayState,
    config: GatewayConfig,
) -> None:
    try:
        register_bot_commands_if_changed(
            telegram=telegram,
            state=state,
            config=config,
        )
    except TelegramApiError:
        return


def _run_install_or_configure(
    *,
    group_chat_id_override: int | None,
    is_install: bool,
) -> None:
    paths = resolve_runtime_paths()
    ensure_runtime_directories(paths)
    existing_env = load_existing_env(paths.env_file)
    answers = prompt_install_answers(
        existing_env=existing_env,
        group_chat_id_override=group_chat_id_override,
        input_func=input,
        secret_input_func=getpass.getpass,
    )
    write_env_file(
        paths.env_file,
        build_managed_env(
            paths=paths,
            answers=answers,
            existing_env=existing_env,
        ),
    )
    action = "Configured" if is_install else "Updated"
    print(f"{action} gateway environment at {paths.env_file}")


if __name__ == "__main__":
    main()
