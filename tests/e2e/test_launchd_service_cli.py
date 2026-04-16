import os
import plistlib
from types import SimpleNamespace

from codex_telegram_gateway import cli
from codex_telegram_gateway.runtime_paths import ensure_runtime_directories, resolve_runtime_paths


def test_service_install_writes_plist_and_bootstraps_launch_agent(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = resolve_runtime_paths(home=tmp_path)
    ensure_runtime_directories(paths)
    paths.env_file.write_text("TELEGRAM_BOT_TOKEN=test\n")
    service_python = paths.install_root / ".venv" / "bin" / "python"
    service_python.parent.mkdir(parents=True)
    service_python.write_text("")
    calls: list[list[str]] = []

    def _fake_run(cmd, check=False, capture_output=False, text=False):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)

    cli.main(["service", "install"])

    plist_payload = plistlib.loads(paths.launchd_plist_path.read_bytes())
    assert plist_payload["Label"] == "com.kangmo.codex-telegram-gateway"
    assert plist_payload["ProgramArguments"] == [
        str(service_python),
        "-m",
        "codex_telegram_gateway.cli",
        "--env-file",
        str(paths.env_file),
        "run-daemon",
    ]
    assert calls == [
        ["launchctl", "bootstrap", f"gui/{os.getuid()}", str(paths.launchd_plist_path)]
    ]
    assert "Installed launchd service" in capsys.readouterr().out


def test_service_status_and_uninstall_use_launchctl_print_and_bootout(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    paths = resolve_runtime_paths(home=tmp_path)
    ensure_runtime_directories(paths)
    paths.launchd_plist_path.write_bytes(b"plist")
    calls: list[list[str]] = []

    def _fake_run(cmd, check=False, capture_output=False, text=False):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="service ok", stderr="")

    monkeypatch.setattr("subprocess.run", _fake_run)

    cli.main(["service", "status"])
    status_out = capsys.readouterr().out
    assert "launchd service: installed" in status_out

    cli.main(["service", "uninstall"])
    uninstall_out = capsys.readouterr().out
    assert "Removed launchd service" in uninstall_out
    assert not paths.launchd_plist_path.exists()
    assert calls == [
        ["launchctl", "print", f"gui/{os.getuid()}/com.kangmo.codex-telegram-gateway"],
        ["launchctl", "bootout", f"gui/{os.getuid()}/com.kangmo.codex-telegram-gateway"],
    ]
