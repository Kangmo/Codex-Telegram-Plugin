import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from codex_telegram_gateway.plugin_installation import upsert_marketplace_plugin
from codex_telegram_gateway.runtime_paths import RuntimePaths

DEFAULT_REPOSITORY_URL = "https://github.com/Kangmo/Codex-Telegram-Plugin"
_PRESERVED_INSTALL_ENTRIES = {".git", ".venv"}


@dataclass(frozen=True)
class SelfUpdateResult:
    """Summary of a completed self-update operation."""

    origin_url: str
    install_root: Path


def discover_origin_url(*, install_root: Path) -> str:
    """Return the git origin URL for the installed checkout when available."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(install_root), "remote", "get-url", "origin"],
            check=True,
            capture_output=True,
            text=True,
        )
    except Exception:
        return DEFAULT_REPOSITORY_URL
    return completed.stdout.strip() or DEFAULT_REPOSITORY_URL


def sync_checkout(*, source_root: Path, install_root: Path) -> None:
    """Synchronize a freshly cloned checkout into the managed install root."""
    for child in install_root.iterdir():
        if child.name in _PRESERVED_INSTALL_ENTRIES:
            continue
        if child.is_dir():
            shutil.rmtree(child)
        else:
            child.unlink()
    for child in source_root.iterdir():
        if child.name in _PRESERVED_INSTALL_ENTRIES:
            continue
        destination = install_root / child.name
        if child.is_dir():
            shutil.copytree(child, destination)
        else:
            shutil.copy2(child, destination)


def perform_self_update(paths: RuntimePaths) -> SelfUpdateResult:
    """Clone the latest origin checkout, sync it into place, and refresh the install."""
    origin_url = discover_origin_url(install_root=paths.install_root)
    with tempfile.TemporaryDirectory(prefix="codex-telegram-update-") as temp_dir:
        clone_root = Path(temp_dir) / "repo"
        subprocess.run(["git", "clone", origin_url, str(clone_root)], check=True)
        sync_checkout(source_root=clone_root, install_root=paths.install_root)
    subprocess.run(
        [
            str(paths.install_root / ".venv" / "bin" / "python"),
            "-m",
            "pip",
            "install",
            "-e",
            str(paths.install_root),
        ],
        check=True,
    )
    upsert_marketplace_plugin(marketplace_path=paths.marketplace_path, paths=paths)
    return SelfUpdateResult(
        origin_url=origin_url,
        install_root=paths.install_root,
    )
