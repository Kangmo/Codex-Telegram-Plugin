import os
import subprocess
from pathlib import Path


def test_install_script_bootstraps_fresh_checkout_with_clone_and_venv(tmp_path) -> None:
    install_root = tmp_path / ".codex-telegram-plugin"
    log_path = tmp_path / "calls.log"
    fake_bin = _write_fake_toolchain(tmp_path, log_path=log_path)

    subprocess.run(
        ["/bin/sh", "install/install.sh"],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_LOG": str(log_path),
            "CODEX_TELEGRAM_REPO_URL": "https://github.com/Kangmo/Codex-Telegram-Plugin",
            "CODEX_TELEGRAM_INSTALL_ROOT": str(install_root),
        },
        check=True,
    )

    assert log_path.read_text().splitlines() == [
        "git:clone https://github.com/Kangmo/Codex-Telegram-Plugin "
        + str(install_root),
        "python3:-m venv " + str(install_root / ".venv"),
        "venv-python:-m pip install --upgrade pip",
        "venv-python:-m pip install -e " + str(install_root),
        "venv-python:-m codex_telegram_gateway.cli install",
        "venv-python:-m codex_telegram_gateway.cli plugin install",
    ]


def test_install_script_refreshes_existing_checkout_with_pull(tmp_path) -> None:
    install_root = tmp_path / ".codex-telegram-plugin"
    (install_root / ".git").mkdir(parents=True)
    log_path = tmp_path / "calls.log"
    fake_bin = _write_fake_toolchain(tmp_path, log_path=log_path)

    subprocess.run(
        ["/bin/sh", "install/install.sh"],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "PATH": f"{fake_bin}:{os.environ['PATH']}",
            "FAKE_LOG": str(log_path),
            "CODEX_TELEGRAM_REPO_URL": "https://github.com/Kangmo/Codex-Telegram-Plugin",
            "CODEX_TELEGRAM_INSTALL_ROOT": str(install_root),
        },
        check=True,
    )

    assert log_path.read_text().splitlines() == [
        "git:-C " + str(install_root) + " pull --ff-only",
        "python3:-m venv " + str(install_root / ".venv"),
        "venv-python:-m pip install --upgrade pip",
        "venv-python:-m pip install -e " + str(install_root),
        "venv-python:-m codex_telegram_gateway.cli install",
        "venv-python:-m codex_telegram_gateway.cli plugin install",
    ]


def test_install_script_fails_when_git_is_missing(tmp_path) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "python3").write_text("#!/bin/sh\nexit 0\n")
    (fake_bin / "python3").chmod(0o755)

    result = subprocess.run(
        ["/bin/sh", "install/install.sh"],
        cwd=Path(__file__).resolve().parents[2],
        env={
            **os.environ,
            "HOME": str(tmp_path),
            "PATH": str(fake_bin),
        },
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 1
    assert result.stderr == "Missing required command: git\n"


def _write_fake_toolchain(tmp_path: Path, *, log_path: Path) -> Path:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    (fake_bin / "git").write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'echo "git:$*" >> "$FAKE_LOG"',
                'if [ "$1" = "clone" ]; then',
                '  mkdir -p "$3/.git"',
                "fi",
            ]
        )
        + "\n"
    )
    (fake_bin / "python3").write_text(
        "\n".join(
            [
                "#!/bin/sh",
                'echo "python3:$*" >> "$FAKE_LOG"',
                'if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then',
                '  mkdir -p "$3/bin"',
                '  cat > "$3/bin/python" <<\'EOF\'',
                "#!/bin/sh",
                'echo "venv-python:$*" >> "$FAKE_LOG"',
                "EOF",
                '  chmod +x "$3/bin/python"',
                "fi",
            ]
        )
        + "\n"
    )
    for tool_path in (fake_bin / "git", fake_bin / "python3"):
        tool_path.chmod(0o755)
    log_path.write_text("")
    return fake_bin
