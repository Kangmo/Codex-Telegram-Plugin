from dataclasses import dataclass

from codex_telegram_gateway.daemon_manager import LocalDaemonStatus
from codex_telegram_gateway.runtime_paths import RuntimePaths


@dataclass(frozen=True)
class OperatorStatusSummary:
    """Operator-facing status summary for install, runtime, and service surfaces."""

    daemon_status: LocalDaemonStatus
    install_root: str
    runtime_home: str
    marketplace_registered: bool
    service_installed: bool


def build_operator_status(
    *,
    paths: RuntimePaths,
    daemon_status: LocalDaemonStatus,
    marketplace_registered: bool,
    service_installed: bool,
) -> OperatorStatusSummary:
    """Build the current operator status summary."""
    return OperatorStatusSummary(
        daemon_status=daemon_status,
        install_root=str(paths.install_root),
        runtime_home=str(paths.runtime_home),
        marketplace_registered=marketplace_registered,
        service_installed=service_installed,
    )


def render_operator_status(summary: OperatorStatusSummary) -> str:
    """Render the operator status summary for CLI output."""
    lines = [
        f"Daemon status: {'running' if summary.daemon_status.running else 'stopped'}",
    ]
    if summary.daemon_status.pid is not None:
        lines.append(f"PID: {summary.daemon_status.pid}")
    lines.extend(
        [
            f"Env file: {summary.daemon_status.env_file}",
            f"Log file: {summary.daemon_status.log_file}",
            f"Install root: {summary.install_root}",
            f"Runtime home: {summary.runtime_home}",
            f"Marketplace: {'registered' if summary.marketplace_registered else 'not registered'}",
            f"launchd service: {'installed' if summary.service_installed else 'not installed'}",
        ]
    )
    return "".join(f"{line}\n" for line in lines)
