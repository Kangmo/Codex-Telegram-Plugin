from codex_telegram_gateway import cli


def test_install_command_writes_managed_env_under_runtime_home(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setenv("HOME", str(tmp_path))
    prompts = iter(["6013473151", "-5251936830"])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "123456:telegram-token")

    cli.main(["install"])

    env_file = tmp_path / ".codex-telegram" / ".env"
    assert env_file.exists()
    assert env_file.read_text() == (
        "TELEGRAM_BOT_TOKEN=123456:telegram-token\n"
        "TELEGRAM_ALLOWED_USER_IDS=6013473151\n"
        "TELEGRAM_DEFAULT_CHAT_ID=-5251936830\n"
        f"CODEX_TELEGRAM_STATE_DB={tmp_path / '.codex-telegram' / 'gateway.db'}\n"
        f"CODEX_TELEGRAM_TOOLBAR_CONFIG={tmp_path / '.codex-telegram' / 'toolbar.toml'}\n"
    )
    assert "Configured gateway environment" in capsys.readouterr().out


def test_configure_command_preserves_existing_values_on_blank_input(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    runtime_home = tmp_path / ".codex-telegram"
    runtime_home.mkdir(parents=True)
    env_file = runtime_home / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=existing-token",
                "TELEGRAM_ALLOWED_USER_IDS=6013473151",
                "TELEGRAM_DEFAULT_CHAT_ID=-5251936830",
                f"CODEX_TELEGRAM_STATE_DB={runtime_home / 'gateway.db'}",
                f"CODEX_TELEGRAM_TOOLBAR_CONFIG={runtime_home / 'toolbar.toml'}",
            ]
        )
        + "\n"
    )
    monkeypatch.setenv("HOME", str(tmp_path))
    prompts = iter(["", ""])
    monkeypatch.setattr("builtins.input", lambda _prompt="": next(prompts))
    monkeypatch.setattr("getpass.getpass", lambda _prompt="": "")

    cli.main(["configure", "--group-chat-id", "-100777"])

    assert env_file.read_text() == (
        "TELEGRAM_BOT_TOKEN=existing-token\n"
        "TELEGRAM_ALLOWED_USER_IDS=6013473151\n"
        "TELEGRAM_DEFAULT_CHAT_ID=-100777\n"
        f"CODEX_TELEGRAM_STATE_DB={runtime_home / 'gateway.db'}\n"
        f"CODEX_TELEGRAM_TOOLBAR_CONFIG={runtime_home / 'toolbar.toml'}\n"
    )
    assert "Updated gateway environment" in capsys.readouterr().out
