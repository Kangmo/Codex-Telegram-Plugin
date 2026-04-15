from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class MarketplaceInstall:
    scope: str
    manifest_path: str
    source: str
    raw_path: str | None = None
    resolved_path: str | None = None


@dataclass(frozen=True)
class UpgradeDiagnostics:
    plugin_name: str
    version: str
    plugin_root: str
    plugin_manifest_path: str
    mcp_manifest_path: str | None
    installs: tuple[MarketplaceInstall, ...] = ()


def discover_upgrade_diagnostics(
    *,
    start_path: Path | None = None,
    home_dir: Path | None = None,
) -> UpgradeDiagnostics:
    plugin_root = _discover_plugin_root(start_path or Path(__file__).resolve())
    plugin_manifest_path = plugin_root / ".codex-plugin" / "plugin.json"
    plugin_manifest = json.loads(plugin_manifest_path.read_text())
    plugin_name = str(plugin_manifest["name"])
    version = str(plugin_manifest["version"])
    mcp_manifest_path = plugin_root / ".mcp.json"
    installs: list[MarketplaceInstall] = []
    home_root = (home_dir or Path.home()).resolve()
    user_marketplace_path = home_root / ".agents" / "plugins" / "marketplace.json"
    repo_marketplace_path = plugin_root / ".agents" / "plugins" / "marketplace.json"
    for scope, marketplace_path in (
        ("repo", repo_marketplace_path),
        ("user", user_marketplace_path),
    ):
        installs.extend(
            _marketplace_installs_for_plugin(
                plugin_name=plugin_name,
                marketplace_path=marketplace_path,
                scope=scope,
            )
        )
    return UpgradeDiagnostics(
        plugin_name=plugin_name,
        version=version,
        plugin_root=str(plugin_root),
        plugin_manifest_path=str(plugin_manifest_path),
        mcp_manifest_path=str(mcp_manifest_path) if mcp_manifest_path.is_file() else None,
        installs=tuple(installs),
    )


def render_upgrade_text(diagnostics: UpgradeDiagnostics) -> str:
    lines = [
        "Gateway upgrade",
        "",
        f"Installed version: `{diagnostics.version}`",
        f"Plugin root: `{diagnostics.plugin_root}`",
        f"Plugin manifest: `{diagnostics.plugin_manifest_path}`",
        (
            f"MCP manifest: `{diagnostics.mcp_manifest_path}`"
            if diagnostics.mcp_manifest_path is not None
            else "MCP manifest: not found"
        ),
        "",
    ]
    if diagnostics.installs:
        lines.append("Marketplace installs:")
        for index, install in enumerate(diagnostics.installs, start=1):
            lines.append(f"{index}. scope `{install.scope}`")
            lines.append(f"manifest `{install.manifest_path}`")
            lines.append(f"source `{install.source}`")
            if install.raw_path is not None:
                lines.append(f"raw path `{install.raw_path}`")
            if install.resolved_path is not None:
                lines.append(f"resolved path `{install.resolved_path}`")
        lines.extend(
            [
                "",
                "Recommended local upgrade steps:",
                "1. Update the plugin source checkout shown above.",
                "2. Restart Codex App so the plugin reloads.",
                "3. Run `/gateway upgrade` again to confirm version and install path.",
            ]
        )
        return "\n".join(lines)
    lines.extend(
        [
            "Marketplace installs: none detected.",
            "",
            "Recommended local upgrade steps:",
            "1. Update the plugin checkout or reinstall it from your plugin marketplace entry.",
            "2. Restart Codex App so the plugin reloads.",
            "3. Run `/gateway upgrade` again to confirm version and install path.",
        ]
    )
    return "\n".join(lines)


def _discover_plugin_root(start_path: Path) -> Path:
    current = start_path.resolve()
    if current.is_file():
        current = current.parent
    for candidate in (current, *current.parents):
        if (candidate / ".codex-plugin" / "plugin.json").is_file():
            return candidate
    raise FileNotFoundError("Could not find `.codex-plugin/plugin.json` from the current plugin path.")


def _marketplace_installs_for_plugin(
    *,
    plugin_name: str,
    marketplace_path: Path,
    scope: str,
) -> list[MarketplaceInstall]:
    if not marketplace_path.is_file():
        return []
    payload = json.loads(marketplace_path.read_text())
    plugins = payload.get("plugins")
    if not isinstance(plugins, list):
        return []
    installs: list[MarketplaceInstall] = []
    for plugin in plugins:
        if not isinstance(plugin, dict):
            continue
        if str(plugin.get("name") or "") != plugin_name:
            continue
        source = plugin.get("source")
        if not isinstance(source, dict):
            installs.append(
                MarketplaceInstall(
                    scope=scope,
                    manifest_path=str(marketplace_path),
                    source="unknown",
                )
            )
            continue
        raw_path = source.get("path")
        raw_path_text = str(raw_path) if isinstance(raw_path, str) and raw_path.strip() else None
        installs.append(
            MarketplaceInstall(
                scope=scope,
                manifest_path=str(marketplace_path),
                source=str(source.get("source") or "unknown"),
                raw_path=raw_path_text,
                resolved_path=(
                    str((marketplace_path.parent / raw_path_text).resolve())
                    if raw_path_text is not None
                    else None
                ),
            )
        )
    return installs
