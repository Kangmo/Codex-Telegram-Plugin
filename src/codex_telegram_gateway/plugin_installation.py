import json
from pathlib import Path

from codex_telegram_gateway.runtime_paths import RuntimePaths

_PLUGIN_NAME = "codex-telegram-gateway"
_DEFAULT_MARKETPLACE = {
    "name": "codex-local",
    "interface": {
        "displayName": "Codex Local Plugins",
    },
    "plugins": [],
}


def load_marketplace_payload(marketplace_path: Path) -> dict[str, object]:
    """Load the personal marketplace payload, or return the default shape."""
    if not marketplace_path.is_file():
        return json.loads(json.dumps(_DEFAULT_MARKETPLACE))
    return json.loads(marketplace_path.read_text())


def build_marketplace_plugin_entry(*, paths: RuntimePaths) -> dict[str, object]:
    """Build the local marketplace entry for this gateway plugin."""
    return {
        "name": _PLUGIN_NAME,
        "source": {
            "source": "local",
            "path": paths.marketplace_source_path,
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }


def upsert_marketplace_plugin(
    *,
    marketplace_path: Path,
    paths: RuntimePaths,
) -> dict[str, object]:
    """Create or update the personal marketplace entry for this gateway plugin."""
    payload = load_marketplace_payload(marketplace_path)
    plugins = [
        plugin
        for plugin in payload.get("plugins", [])
        if isinstance(plugin, dict) and str(plugin.get("name") or "") != _PLUGIN_NAME
    ]
    plugins.append(build_marketplace_plugin_entry(paths=paths))
    payload["plugins"] = plugins
    marketplace_path.parent.mkdir(parents=True, exist_ok=True)
    marketplace_path.write_text(json.dumps(payload, indent=2))
    return payload


def find_marketplace_plugin_entry(
    *,
    marketplace_path: Path,
) -> dict[str, object] | None:
    """Return the registered plugin entry from the personal marketplace payload."""
    payload = load_marketplace_payload(marketplace_path)
    for plugin in payload.get("plugins", []):
        if not isinstance(plugin, dict):
            continue
        if str(plugin.get("name") or "") == _PLUGIN_NAME:
            return plugin
    return None
