import json

from codex_telegram_gateway import cli


def test_plugin_install_command_writes_personal_marketplace_entry(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))

    cli.main(["plugin", "install"])

    marketplace_path = tmp_path / ".agents" / "plugins" / "marketplace.json"
    assert json.loads(marketplace_path.read_text()) == {
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
    assert "Registered plugin marketplace entry" in capsys.readouterr().out


def test_plugin_status_command_reports_registered_marketplace_entry(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    marketplace_path = tmp_path / ".agents" / "plugins" / "marketplace.json"
    marketplace_path.parent.mkdir(parents=True)
    marketplace_path.write_text(
        json.dumps(
            {
                "name": "codex-local",
                "interface": {"displayName": "Codex Local Plugins"},
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
        )
    )

    cli.main(["plugin", "status"])

    assert capsys.readouterr().out == (
        "Marketplace file: "
        + f"{marketplace_path}\n"
        + "Plugin: codex-telegram-gateway\n"
        + "Registered: yes\n"
        + "Source path: ./.codex-telegram-plugin\n"
    )
