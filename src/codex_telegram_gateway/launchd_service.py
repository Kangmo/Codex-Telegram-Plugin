import os
import plistlib
import subprocess

from codex_telegram_gateway.runtime_paths import RuntimePaths

SERVICE_LABEL = "com.kangmo.codex-telegram-gateway"


def build_launchctl_domain() -> str:
    """Return the current-user launchctl bootstrap domain."""
    return f"gui/{os.getuid()}"


def render_launchd_plist(*, paths: RuntimePaths) -> bytes:
    """Render the launchd plist payload for the local daemon."""
    payload = {
        "Label": SERVICE_LABEL,
        "ProgramArguments": [
            str(paths.install_root / ".venv" / "bin" / "python"),
            "-m",
            "codex_telegram_gateway.cli",
            "--env-file",
            str(paths.env_file),
            "run-daemon",
        ],
        "WorkingDirectory": str(paths.install_root),
        "RunAtLoad": True,
        "KeepAlive": True,
        "StandardOutPath": str(paths.daemon_log_path),
        "StandardErrorPath": str(paths.daemon_log_path),
        "EnvironmentVariables": {
            "HOME": str(paths.install_root.parent),
        },
    }
    return plistlib.dumps(payload)


def install_launchd_service(*, paths: RuntimePaths) -> None:
    """Write the launchd plist and bootstrap it for the current user."""
    paths.launchd_plist_path.parent.mkdir(parents=True, exist_ok=True)
    paths.launchd_plist_path.write_bytes(render_launchd_plist(paths=paths))
    subprocess.run(
        ["launchctl", "bootstrap", build_launchctl_domain(), str(paths.launchd_plist_path)],
        check=True,
    )


def uninstall_launchd_service(*, paths: RuntimePaths) -> None:
    """Boot out and remove the launchd plist for the current user."""
    subprocess.run(
        ["launchctl", "bootout", f"{build_launchctl_domain()}/{SERVICE_LABEL}"],
        check=True,
    )
    paths.launchd_plist_path.unlink(missing_ok=True)


def start_launchd_service(*, paths: RuntimePaths) -> None:
    """Bootstrap the launchd service using the existing plist."""
    subprocess.run(
        ["launchctl", "bootstrap", build_launchctl_domain(), str(paths.launchd_plist_path)],
        check=True,
    )


def stop_launchd_service() -> None:
    """Stop the current-user launchd service."""
    subprocess.run(
        ["launchctl", "bootout", f"{build_launchctl_domain()}/{SERVICE_LABEL}"],
        check=True,
    )


def print_launchd_service_status() -> subprocess.CompletedProcess:
    """Query launchd for the current service state."""
    return subprocess.run(
        ["launchctl", "print", f"{build_launchctl_domain()}/{SERVICE_LABEL}"],
        check=True,
        capture_output=True,
        text=True,
    )
