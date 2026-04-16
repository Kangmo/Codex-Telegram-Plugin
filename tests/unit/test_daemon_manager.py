from pathlib import Path

from codex_telegram_gateway.daemon_manager import (
    _is_process_running,
    build_daemon_command,
    parse_pid_file,
    read_log_tail,
    start_daemon,
    stop_daemon,
)
from codex_telegram_gateway.runtime_paths import resolve_runtime_paths


def test_build_daemon_command_uses_installed_venv_python_and_managed_env(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)

    assert build_daemon_command(paths=paths) == [
        str(paths.install_root / ".venv" / "bin" / "python"),
        "-m",
        "codex_telegram_gateway.cli",
        "--env-file",
        str(paths.env_file),
        "run-daemon",
    ]


def test_parse_pid_file_returns_none_for_missing_or_invalid_files(tmp_path) -> None:
    assert parse_pid_file(tmp_path / "missing.pid") is None

    invalid_file = tmp_path / "invalid.pid"
    invalid_file.write_text("abc\n")

    assert parse_pid_file(invalid_file) is None


def test_start_daemon_rejects_missing_env_file(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)

    try:
        start_daemon(paths=paths)
    except ValueError as exc:
        assert str(exc) == f"Missing gateway environment file: {paths.env_file}"
    else:
        raise AssertionError("start_daemon accepted a missing env file")


def test_start_daemon_cleans_stale_pid_before_missing_python_error(tmp_path, monkeypatch) -> None:
    paths = resolve_runtime_paths(home=tmp_path)
    paths.env_file.parent.mkdir(parents=True)
    paths.env_file.write_text("TELEGRAM_BOT_TOKEN=test\n")
    paths.daemon_pid_path.parent.mkdir(parents=True)
    paths.daemon_pid_path.write_text("123\n")
    monkeypatch.setattr("codex_telegram_gateway.daemon_manager._is_process_running", lambda _pid: False)

    try:
        start_daemon(paths=paths)
    except ValueError as exc:
        assert str(exc) == (
            f"Missing installed daemon Python: {paths.install_root / '.venv' / 'bin' / 'python'}"
        )
    else:
        raise AssertionError("start_daemon accepted a missing daemon python")

    assert not paths.daemon_pid_path.exists()


def test_stop_daemon_returns_current_status_when_pid_is_missing_or_stale(tmp_path, monkeypatch) -> None:
    paths = resolve_runtime_paths(home=tmp_path)

    status = stop_daemon(paths=paths)
    assert status.running is False
    assert status.pid is None

    paths.daemon_pid_path.parent.mkdir(parents=True)
    paths.daemon_pid_path.write_text("123\n")
    monkeypatch.setattr("codex_telegram_gateway.daemon_manager._is_process_running", lambda _pid: False)

    status = stop_daemon(paths=paths)
    assert status.running is False
    assert status.pid is None
    assert not paths.daemon_pid_path.exists()


def test_read_log_tail_returns_empty_for_missing_or_empty_logs(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)
    assert read_log_tail(paths=paths) == ""

    paths.daemon_log_path.parent.mkdir(parents=True)
    paths.daemon_log_path.write_text("")
    assert read_log_tail(paths=paths) == ""


def test_is_process_running_handles_waitpid_and_kill_failures(monkeypatch) -> None:
    monkeypatch.setattr("os.waitpid", lambda _pid, _flags: (_pid, 0))
    assert _is_process_running(123) is False

    def _raise_child_process_error(_pid, _flags):
        raise ChildProcessError

    def _raise_os_error(_pid, _signal):
        raise OSError

    monkeypatch.setattr("os.waitpid", _raise_child_process_error)
    monkeypatch.setattr("os.kill", _raise_os_error)
    assert _is_process_running(123) is False
