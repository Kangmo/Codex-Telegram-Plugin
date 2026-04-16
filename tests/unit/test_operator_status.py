from codex_telegram_gateway.daemon_manager import LocalDaemonStatus
from codex_telegram_gateway.operator_status import (
    build_operator_status,
    render_operator_status,
)
from codex_telegram_gateway.runtime_paths import resolve_runtime_paths


def test_render_operator_status_includes_daemon_runtime_and_install_flags(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)
    summary = build_operator_status(
        paths=paths,
        daemon_status=LocalDaemonStatus(
            pid=None,
            running=False,
            env_file=paths.env_file,
            log_file=paths.daemon_log_path,
        ),
        marketplace_registered=False,
        service_installed=False,
    )

    assert render_operator_status(summary) == (
        "Daemon status: stopped\n"
        f"Env file: {paths.env_file}\n"
        f"Log file: {paths.daemon_log_path}\n"
        f"Install root: {paths.install_root}\n"
        f"Runtime home: {paths.runtime_home}\n"
        "Marketplace: not registered\n"
        "launchd service: not installed\n"
    )
