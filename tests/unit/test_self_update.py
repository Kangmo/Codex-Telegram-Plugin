from pathlib import Path
from types import SimpleNamespace

from codex_telegram_gateway.self_update import (
    DEFAULT_REPOSITORY_URL,
    discover_origin_url,
    perform_self_update,
    sync_checkout,
)
from codex_telegram_gateway.runtime_paths import resolve_runtime_paths


def test_discover_origin_url_reads_git_remote(monkeypatch, tmp_path) -> None:
    install_root = tmp_path / "repo"
    install_root.mkdir()

    def _fake_run(cmd, check, capture_output, text):
        assert cmd == ["git", "-C", str(install_root), "remote", "get-url", "origin"]
        return SimpleNamespace(stdout="https://github.com/Kangmo/Codex-Telegram-Plugin\n")

    monkeypatch.setattr("subprocess.run", _fake_run)

    assert discover_origin_url(install_root=install_root) == "https://github.com/Kangmo/Codex-Telegram-Plugin"


def test_discover_origin_url_falls_back_to_default_when_git_remote_fails(monkeypatch, tmp_path) -> None:
    install_root = tmp_path / "repo"
    install_root.mkdir()

    def _fake_run(cmd, check, capture_output, text):
        raise RuntimeError("git unavailable")

    monkeypatch.setattr("subprocess.run", _fake_run)

    assert discover_origin_url(install_root=install_root) == DEFAULT_REPOSITORY_URL


def test_sync_checkout_replaces_files_but_preserves_dot_git_and_venv(tmp_path) -> None:
    source_root = tmp_path / "source"
    source_root.mkdir()
    (source_root / "README.md").write_text("new\n")
    (source_root / "src").mkdir()
    (source_root / "src" / "app.py").write_text("print('new')\n")
    (source_root / ".venv").mkdir()
    install_root = tmp_path / "install"
    install_root.mkdir()
    (install_root / "README.md").write_text("old\n")
    (install_root / "old.txt").write_text("remove me\n")
    (install_root / ".git").mkdir()
    (install_root / ".git" / "config").write_text("keep git\n")
    (install_root / ".venv").mkdir()
    (install_root / ".venv" / "marker").write_text("keep venv\n")

    sync_checkout(source_root=source_root, install_root=install_root)

    assert (install_root / "README.md").read_text() == "new\n"
    assert (install_root / "src" / "app.py").read_text() == "print('new')\n"
    assert not (install_root / "old.txt").exists()
    assert (install_root / ".git" / "config").read_text() == "keep git\n"
    assert (install_root / ".venv" / "marker").read_text() == "keep venv\n"


def test_perform_self_update_clones_syncs_reinstalls_and_refreshes_marketplace(
    tmp_path,
    monkeypatch,
) -> None:
    paths = resolve_runtime_paths(home=tmp_path)
    paths.install_root.mkdir()
    (paths.install_root / ".venv").mkdir()
    (paths.install_root / ".venv" / "keep").write_text("venv\n")
    recorded_commands: list[list[str]] = []
    marketplace_calls: list[tuple[Path, Path]] = []

    class _StaticTempDir:
        def __init__(self, path: Path) -> None:
            self._path = path

        def __enter__(self) -> str:
            self._path.mkdir(parents=True, exist_ok=True)
            return str(self._path)

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    def _fake_run(cmd, check, capture_output=False, text=False):
        recorded_commands.append(list(cmd))
        if cmd[:2] == ["git", "clone"]:
            clone_root = Path(cmd[3])
            clone_root.mkdir(parents=True)
            (clone_root / "README.md").write_text("updated\n")
        return SimpleNamespace(stdout="")

    monkeypatch.setattr(
        "codex_telegram_gateway.self_update.discover_origin_url",
        lambda install_root: "https://github.com/Kangmo/Codex-Telegram-Plugin",
    )
    monkeypatch.setattr(
        "codex_telegram_gateway.self_update.tempfile.TemporaryDirectory",
        lambda prefix: _StaticTempDir(tmp_path / "update-temp"),
    )
    monkeypatch.setattr("subprocess.run", _fake_run)
    monkeypatch.setattr(
        "codex_telegram_gateway.self_update.upsert_marketplace_plugin",
        lambda marketplace_path, paths: marketplace_calls.append((marketplace_path, paths.install_root)),
    )

    result = perform_self_update(paths)

    assert result.origin_url == "https://github.com/Kangmo/Codex-Telegram-Plugin"
    assert result.install_root == paths.install_root
    assert (paths.install_root / "README.md").read_text() == "updated\n"
    assert (paths.install_root / ".venv" / "keep").read_text() == "venv\n"
    assert recorded_commands == [
        [
            "git",
            "clone",
            "https://github.com/Kangmo/Codex-Telegram-Plugin",
            str(tmp_path / "update-temp" / "repo"),
        ],
        [
            str(paths.install_root / ".venv" / "bin" / "python"),
            "-m",
            "pip",
            "install",
            "-e",
            str(paths.install_root),
        ],
    ]
    assert marketplace_calls == [(paths.marketplace_path, paths.install_root)]
