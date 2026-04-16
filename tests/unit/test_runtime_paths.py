from pathlib import Path

from codex_telegram_gateway.runtime_paths import (
    DEFAULT_LAUNCHD_LABEL,
    ensure_runtime_directories,
    resolve_runtime_paths,
)


def test_resolve_runtime_paths_uses_managed_defaults_under_home(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)

    assert paths.install_root == tmp_path / ".codex-telegram-plugin"
    assert paths.runtime_home == tmp_path / ".codex-telegram"
    assert paths.env_file == tmp_path / ".codex-telegram" / ".env"
    assert paths.state_database_path == tmp_path / ".codex-telegram" / "gateway.db"
    assert paths.toolbar_config_path == tmp_path / ".codex-telegram" / "toolbar.toml"
    assert paths.logs_dir == tmp_path / ".codex-telegram" / "logs"
    assert paths.daemon_log_path == tmp_path / ".codex-telegram" / "logs" / "gateway.log"
    assert paths.run_dir == tmp_path / ".codex-telegram" / "run"
    assert paths.daemon_pid_path == tmp_path / ".codex-telegram" / "run" / "gateway.pid"
    assert paths.launch_agents_dir == tmp_path / "Library" / "LaunchAgents"
    assert paths.launchd_plist_path == (
        tmp_path / "Library" / "LaunchAgents" / f"{DEFAULT_LAUNCHD_LABEL}.plist"
    )
    assert paths.marketplace_path == tmp_path / ".agents" / "plugins" / "marketplace.json"


def test_resolve_runtime_paths_renders_home_relative_marketplace_source(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)

    assert paths.marketplace_source_path == "./.codex-telegram-plugin"


def test_resolve_runtime_paths_respects_custom_install_root_and_runtime_home(tmp_path) -> None:
    install_root = tmp_path / "src" / "gateway"
    runtime_home = tmp_path / "var" / "codex-telegram"

    paths = resolve_runtime_paths(
        home=tmp_path,
        install_root=install_root,
        runtime_home=runtime_home,
    )

    assert paths.install_root == install_root
    assert paths.runtime_home == runtime_home
    assert paths.env_file == runtime_home / ".env"
    assert paths.state_database_path == runtime_home / "gateway.db"
    assert paths.marketplace_source_path == "./src/gateway"


def test_resolve_runtime_paths_uses_absolute_marketplace_source_outside_home(tmp_path) -> None:
    external_root = tmp_path.parent / "external-install-root"

    paths = resolve_runtime_paths(
        home=tmp_path,
        install_root=external_root,
    )

    assert paths.marketplace_source_path == str(external_root.resolve())


def test_ensure_runtime_directories_creates_managed_runtime_and_operator_dirs(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)

    ensure_runtime_directories(paths)

    assert paths.runtime_home.is_dir()
    assert paths.logs_dir.is_dir()
    assert paths.run_dir.is_dir()
    assert paths.marketplace_path.parent.is_dir()
    assert paths.launch_agents_dir.is_dir()
