import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from codex_telegram_gateway.runtime_paths import RuntimePaths


@dataclass(frozen=True)
class LocalDaemonStatus:
    """Current local daemon state derived from pid and log files."""

    pid: int | None
    running: bool
    env_file: Path
    log_file: Path


def build_daemon_command(*, paths: RuntimePaths) -> list[str]:
    """Build the local background daemon command for the installed checkout."""
    return [
        str(paths.install_root / ".venv" / "bin" / "python"),
        "-m",
        "codex_telegram_gateway.cli",
        "--env-file",
        str(paths.env_file),
        "run-daemon",
    ]


def parse_pid_file(pid_path: Path) -> int | None:
    """Read a daemon pid file and return a valid integer pid when present."""
    if not pid_path.is_file():
        return None
    try:
        return int(pid_path.read_text().strip())
    except ValueError:
        return None


def get_daemon_status(*, paths: RuntimePaths) -> LocalDaemonStatus:
    """Return the current local daemon status."""
    pid = parse_pid_file(paths.daemon_pid_path)
    return LocalDaemonStatus(
        pid=pid,
        running=pid is not None and _is_process_running(pid),
        env_file=paths.env_file,
        log_file=paths.daemon_log_path,
    )


def start_daemon(*, paths: RuntimePaths) -> LocalDaemonStatus:
    """Start the local daemon if it is not already running."""
    status = get_daemon_status(paths=paths)
    if status.running:
        return status
    if status.pid is not None and not status.running:
        paths.daemon_pid_path.unlink(missing_ok=True)
    if not paths.env_file.is_file():
        raise ValueError(f"Missing gateway environment file: {paths.env_file}")
    daemon_command = build_daemon_command(paths=paths)
    daemon_python = Path(daemon_command[0])
    if not daemon_python.is_file():
        raise ValueError(f"Missing installed daemon Python: {daemon_python}")
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    with paths.daemon_log_path.open("ab", buffering=0) as log_handle:
        process = subprocess.Popen(
            daemon_command,
            cwd=paths.install_root,
            stdout=log_handle,
            stderr=log_handle,
            start_new_session=True,
        )
    paths.daemon_pid_path.write_text(f"{process.pid}\n")
    return get_daemon_status(paths=paths)


def stop_daemon(*, paths: RuntimePaths) -> LocalDaemonStatus:
    """Stop the local daemon if it is running."""
    status = get_daemon_status(paths=paths)
    if status.pid is None:
        return status
    if not status.running:
        paths.daemon_pid_path.unlink(missing_ok=True)
        return get_daemon_status(paths=paths)
    os.kill(status.pid, signal.SIGTERM)
    deadline = time.time() + 5.0
    while time.time() < deadline:
        if not _is_process_running(status.pid):
            paths.daemon_pid_path.unlink(missing_ok=True)
            return get_daemon_status(paths=paths)
        time.sleep(0.05)
    os.kill(status.pid, signal.SIGKILL)
    kill_deadline = time.time() + 1.0
    while time.time() < kill_deadline:
        if not _is_process_running(status.pid):
            paths.daemon_pid_path.unlink(missing_ok=True)
            return get_daemon_status(paths=paths)
        time.sleep(0.05)
    raise ValueError(f"Failed to stop local daemon pid {status.pid}")


def read_log_tail(*, paths: RuntimePaths, lines: int = 50) -> str:
    """Return the last N log lines for the local daemon."""
    if not paths.daemon_log_path.is_file():
        return ""
    content = paths.daemon_log_path.read_text(errors="replace").splitlines()
    if not content:
        return ""
    return "".join(f"{line}\n" for line in content[-lines:])


def _is_process_running(pid: int) -> bool:
    try:
        waited_pid, _status = os.waitpid(pid, os.WNOHANG)
    except ChildProcessError:
        waited_pid = 0
    if waited_pid == pid:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True
