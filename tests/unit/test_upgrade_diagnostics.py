import json
from pathlib import Path

from codex_telegram_gateway.upgrade_diagnostics import (
    MarketplaceInstall,
    UpgradeDiagnostics,
    discover_upgrade_diagnostics,
    render_upgrade_text,
)


def test_render_upgrade_text_with_marketplace_install() -> None:
    text = render_upgrade_text(
        UpgradeDiagnostics(
            plugin_name="codex-telegram-gateway",
            version="0.1.0",
            plugin_root="/tmp/codex-telegram",
            plugin_manifest_path="/tmp/codex-telegram/.codex-plugin/plugin.json",
            mcp_manifest_path="/tmp/codex-telegram/.mcp.json",
            installs=(
                MarketplaceInstall(
                    scope="user",
                    manifest_path="/tmp/home/.agents/plugins/marketplace.json",
                    source="local",
                    raw_path="../plugin-source/codex-telegram-gateway",
                    resolved_path="/tmp/home/.agents/plugin-source/codex-telegram-gateway",
                ),
            ),
        )
    )

    assert text == (
        "Gateway upgrade\n\n"
        "Installed version: `0.1.0`\n"
        "Plugin root: `/tmp/codex-telegram`\n"
        "Plugin manifest: `/tmp/codex-telegram/.codex-plugin/plugin.json`\n"
        "MCP manifest: `/tmp/codex-telegram/.mcp.json`\n\n"
        "Marketplace installs:\n"
        "1. scope `user`\n"
        "manifest `/tmp/home/.agents/plugins/marketplace.json`\n"
        "source `local`\n"
        "raw path `../plugin-source/codex-telegram-gateway`\n"
        "resolved path `/tmp/home/.agents/plugin-source/codex-telegram-gateway`\n\n"
        "Recommended local upgrade steps:\n"
        "1. Update the plugin source checkout shown above.\n"
        "2. Restart Codex App so the plugin reloads.\n"
        "3. Run `/gateway upgrade` again to confirm version and install path."
    )


def test_render_upgrade_text_without_marketplace_install() -> None:
    text = render_upgrade_text(
        UpgradeDiagnostics(
            plugin_name="codex-telegram-gateway",
            version="0.1.0",
            plugin_root="/tmp/codex-telegram",
            plugin_manifest_path="/tmp/codex-telegram/.codex-plugin/plugin.json",
            mcp_manifest_path=None,
        )
    )

    assert text == (
        "Gateway upgrade\n\n"
        "Installed version: `0.1.0`\n"
        "Plugin root: `/tmp/codex-telegram`\n"
        "Plugin manifest: `/tmp/codex-telegram/.codex-plugin/plugin.json`\n"
        "MCP manifest: not found\n\n"
        "Marketplace installs: none detected.\n\n"
        "Recommended local upgrade steps:\n"
        "1. Update the plugin checkout or reinstall it from your plugin marketplace entry.\n"
        "2. Restart Codex App so the plugin reloads.\n"
        "3. Run `/gateway upgrade` again to confirm version and install path."
    )


def test_discover_upgrade_diagnostics_reads_plugin_manifest_and_user_marketplace(tmp_path) -> None:
    plugin_root = tmp_path / "repo"
    plugin_root.mkdir()
    (plugin_root / ".codex-plugin").mkdir()
    (plugin_root / ".codex-plugin" / "plugin.json").write_text(
        json.dumps(
            {
                "name": "codex-telegram-gateway",
                "version": "9.9.9",
            }
        )
    )
    (plugin_root / ".mcp.json").write_text(json.dumps({"mcpServers": {}}))
    start_path = plugin_root / "src" / "codex_telegram_gateway"
    start_path.mkdir(parents=True)

    fake_home = tmp_path / "home"
    marketplace_path = fake_home / ".agents" / "plugins" / "marketplace.json"
    marketplace_path.parent.mkdir(parents=True)
    marketplace_path.write_text(
        json.dumps(
            {
                "plugins": [
                    {
                        "name": "codex-telegram-gateway",
                        "source": {
                            "source": "local",
                            "path": "../plugin-source/codex-telegram-gateway",
                        },
                    }
                ]
            }
        )
    )

    diagnostics = discover_upgrade_diagnostics(
        start_path=start_path,
        home_dir=fake_home,
    )

    assert diagnostics == UpgradeDiagnostics(
        plugin_name="codex-telegram-gateway",
        version="9.9.9",
        plugin_root=str(plugin_root),
        plugin_manifest_path=str(plugin_root / ".codex-plugin" / "plugin.json"),
        mcp_manifest_path=str(plugin_root / ".mcp.json"),
        installs=(
            MarketplaceInstall(
                scope="user",
                manifest_path=str(marketplace_path),
                source="local",
                raw_path="../plugin-source/codex-telegram-gateway",
                resolved_path=str((marketplace_path.parent / "../plugin-source/codex-telegram-gateway").resolve()),
            ),
        ),
    )
