from dataclasses import dataclass
from pathlib import Path


DEFAULT_INSTALL_DIRNAME = ".codex-telegram-plugin"
DEFAULT_RUNTIME_DIRNAME = ".codex-telegram"
DEFAULT_LAUNCHD_LABEL = "com.kangmo.codex-telegram-gateway"


@dataclass(frozen=True)
class RuntimePaths:
    """Managed install, runtime, and operator paths for the gateway."""

    install_root: Path
    runtime_home: Path
    env_file: Path
    state_database_path: Path
    toolbar_config_path: Path
    logs_dir: Path
    daemon_log_path: Path
    run_dir: Path
    daemon_pid_path: Path
    launch_agents_dir: Path
    launchd_plist_path: Path
    marketplace_path: Path
    marketplace_source_path: str


def resolve_runtime_paths(
    *,
    home: Path | None = None,
    install_root: Path | None = None,
    runtime_home: Path | None = None,
) -> RuntimePaths:
    """Resolve the managed install and runtime paths."""
    resolved_home = (home or Path.home()).expanduser().resolve()
    resolved_install_root = (
        install_root if install_root is not None else resolved_home / DEFAULT_INSTALL_DIRNAME
    ).expanduser().resolve()
    resolved_runtime_home = (
        runtime_home if runtime_home is not None else resolved_home / DEFAULT_RUNTIME_DIRNAME
    ).expanduser().resolve()
    launch_agents_dir = resolved_home / "Library" / "LaunchAgents"
    marketplace_path = resolved_home / ".agents" / "plugins" / "marketplace.json"
    return RuntimePaths(
        install_root=resolved_install_root,
        runtime_home=resolved_runtime_home,
        env_file=resolved_runtime_home / ".env",
        state_database_path=resolved_runtime_home / "gateway.db",
        toolbar_config_path=resolved_runtime_home / "toolbar.toml",
        logs_dir=resolved_runtime_home / "logs",
        daemon_log_path=resolved_runtime_home / "logs" / "gateway.log",
        run_dir=resolved_runtime_home / "run",
        daemon_pid_path=resolved_runtime_home / "run" / "gateway.pid",
        launch_agents_dir=launch_agents_dir,
        launchd_plist_path=launch_agents_dir / f"{DEFAULT_LAUNCHD_LABEL}.plist",
        marketplace_path=marketplace_path,
        marketplace_source_path=_marketplace_source_path(
            home=resolved_home,
            install_root=resolved_install_root,
        ),
    )


def ensure_runtime_directories(paths: RuntimePaths) -> None:
    """Create the managed directories used by runtime and operator commands."""
    for directory in (
        paths.runtime_home,
        paths.logs_dir,
        paths.run_dir,
        paths.marketplace_path.parent,
        paths.launch_agents_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)


def _marketplace_source_path(*, home: Path, install_root: Path) -> str:
    try:
        relative_path = install_root.relative_to(home)
    except ValueError:
        return str(install_root)
    return f"./{relative_path.as_posix()}"
