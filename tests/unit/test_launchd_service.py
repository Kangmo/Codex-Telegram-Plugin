import os
import plistlib
from types import SimpleNamespace

from codex_telegram_gateway.launchd_service import (
    build_launchctl_domain,
    render_launchd_plist,
)
from codex_telegram_gateway.runtime_paths import resolve_runtime_paths


def test_render_launchd_plist_contains_program_arguments_and_log_paths(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)

    payload = plistlib.loads(render_launchd_plist(paths=paths))

    assert payload == {
        "Label": "com.kangmo.codex-telegram-gateway",
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
            "HOME": str(tmp_path),
        },
    }


def test_build_launchctl_domain_uses_current_uid(monkeypatch) -> None:
    monkeypatch.setattr("os.getuid", lambda: 501)

    assert build_launchctl_domain() == "gui/501"
