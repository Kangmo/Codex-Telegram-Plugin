import os
import stat
import time

from codex_telegram_gateway import cli
from codex_telegram_gateway.runtime_paths import ensure_runtime_directories, resolve_runtime_paths


def test_local_daemon_start_status_logs_and_stop(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = resolve_runtime_paths(home=tmp_path)
    ensure_runtime_directories(paths)
    paths.env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_USER_IDS=6013473151",
                "TELEGRAM_DEFAULT_CHAT_ID=-5251936830",
            ]
        )
        + "\n"
    )
    fake_python = paths.install_root / ".venv" / "bin" / "python"
    fake_python.parent.mkdir(parents=True)
    fake_python.write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'echo "fake daemon started: $*"',
                'trap "exit 0" TERM INT',
                "while :; do",
                "  sleep 1",
                "done",
            ]
        )
        + "\n"
    )
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)

    try:
        cli.main(["start"])
        out = capsys.readouterr().out
        assert "Started local daemon" in out
        assert paths.daemon_pid_path.exists()

        deadline = time.time() + 2.0
        while time.time() < deadline:
            if paths.daemon_log_path.is_file() and "fake daemon started:" in paths.daemon_log_path.read_text():
                break
            time.sleep(0.05)

        cli.main(["status"])
        assert capsys.readouterr().out.startswith("Daemon status: running\n")

        cli.main(["logs"])
        assert "fake daemon started:" in capsys.readouterr().out
    finally:
        cli.main(["stop"])
        capsys.readouterr()

    assert not paths.daemon_pid_path.exists()
    cli.main(["status"])
    assert capsys.readouterr().out.startswith("Daemon status: stopped\n")
