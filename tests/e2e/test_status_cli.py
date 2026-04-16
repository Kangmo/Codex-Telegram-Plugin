from codex_telegram_gateway import cli
from codex_telegram_gateway.daemon_manager import LocalDaemonStatus
from codex_telegram_gateway.runtime_paths import ensure_runtime_directories, resolve_runtime_paths


def test_status_command_renders_operator_summary(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = resolve_runtime_paths(home=tmp_path)
    ensure_runtime_directories(paths)
    paths.env_file.write_text("TELEGRAM_BOT_TOKEN=test\n")
    paths.marketplace_path.write_text(
        '{"name":"codex-local","interface":{"displayName":"Codex Local Plugins"},"plugins":[{"name":"codex-telegram-gateway","source":{"source":"local","path":"./.codex-telegram-plugin"}}]}'
    )
    paths.launchd_plist_path.write_text("plist")
    monkeypatch.setattr(
        "codex_telegram_gateway.cli.get_daemon_status",
        lambda paths: LocalDaemonStatus(
            pid=4321,
            running=True,
            env_file=paths.env_file,
            log_file=paths.daemon_log_path,
        ),
    )

    cli.main(["status"])

    assert capsys.readouterr().out == (
        "Daemon status: running\n"
        "PID: 4321\n"
        f"Env file: {paths.env_file}\n"
        f"Log file: {paths.daemon_log_path}\n"
        f"Install root: {paths.install_root}\n"
        f"Runtime home: {paths.runtime_home}\n"
        "Marketplace: registered\n"
        "launchd service: installed\n"
    )
