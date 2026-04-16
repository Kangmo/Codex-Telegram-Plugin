import json

from codex_telegram_gateway.plugin_installation import (
    build_marketplace_plugin_entry,
    find_marketplace_plugin_entry,
    load_marketplace_payload,
    upsert_marketplace_plugin,
)
from codex_telegram_gateway.runtime_paths import resolve_runtime_paths


def test_upsert_marketplace_plugin_creates_default_marketplace_payload(tmp_path) -> None:
    marketplace_path = tmp_path / "marketplace.json"
    paths = resolve_runtime_paths(home=tmp_path)

    payload = upsert_marketplace_plugin(marketplace_path=marketplace_path, paths=paths)

    assert payload == {
        "name": "codex-local",
        "interface": {
            "displayName": "Codex Local Plugins",
        },
        "plugins": [
            {
                "name": "codex-telegram-gateway",
                "source": {
                    "source": "local",
                    "path": "./.codex-telegram-plugin",
                },
                "policy": {
                    "installation": "AVAILABLE",
                    "authentication": "ON_INSTALL",
                },
                "category": "Productivity",
            }
        ],
    }
    assert json.loads(marketplace_path.read_text()) == payload


def test_upsert_marketplace_plugin_preserves_unrelated_entries(tmp_path) -> None:
    marketplace_path = tmp_path / "marketplace.json"
    marketplace_path.write_text(
        json.dumps(
            {
                "name": "codex-local",
                "interface": {"displayName": "Codex Local Plugins"},
                "plugins": [
                    {
                        "name": "other-plugin",
                        "source": {"source": "local", "path": "./other-plugin"},
                    }
                ],
            }
        )
    )
    paths = resolve_runtime_paths(home=tmp_path)

    payload = upsert_marketplace_plugin(marketplace_path=marketplace_path, paths=paths)

    assert payload["plugins"] == [
        {
            "name": "other-plugin",
            "source": {"source": "local", "path": "./other-plugin"},
        },
        {
            "name": "codex-telegram-gateway",
            "source": {
                "source": "local",
                "path": "./.codex-telegram-plugin",
            },
            "policy": {
                "installation": "AVAILABLE",
                "authentication": "ON_INSTALL",
            },
            "category": "Productivity",
        },
    ]


def test_build_marketplace_plugin_entry_uses_runtime_path_model(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)

    assert build_marketplace_plugin_entry(paths=paths) == {
        "name": "codex-telegram-gateway",
        "source": {
            "source": "local",
            "path": "./.codex-telegram-plugin",
        },
        "policy": {
            "installation": "AVAILABLE",
            "authentication": "ON_INSTALL",
        },
        "category": "Productivity",
    }


def test_load_marketplace_payload_returns_default_when_missing(tmp_path) -> None:
    assert load_marketplace_payload(tmp_path / "missing.json") == {
        "name": "codex-local",
        "interface": {
            "displayName": "Codex Local Plugins",
        },
        "plugins": [],
    }


def test_find_marketplace_plugin_entry_returns_none_for_unrelated_plugins(tmp_path) -> None:
    marketplace_path = tmp_path / "marketplace.json"
    marketplace_path.write_text(
        json.dumps(
            {
                "name": "codex-local",
                "interface": {"displayName": "Codex Local Plugins"},
                "plugins": [
                    "invalid-entry",
                    {
                        "name": "other-plugin",
                        "source": {"source": "local", "path": "./other-plugin"},
                    },
                ],
            }
        )
    )

    assert find_marketplace_plugin_entry(marketplace_path=marketplace_path) is None
