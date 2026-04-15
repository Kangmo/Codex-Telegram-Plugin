from codex_telegram_gateway.commands_catalog import (
    build_bot_commands,
    register_bot_commands_if_changed,
)
from tests.unit.support import DummyState, DummyTelegramClient


def test_build_bot_commands_merges_configured_and_observed_passthrough_commands() -> None:
    from codex_telegram_gateway.config import GatewayConfig

    config = GatewayConfig(
        telegram_bot_token="test-token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
        telegram_menu_passthrough_commands=("help", "status"),
    )

    commands = build_bot_commands(config, observed_passthrough_commands=("status", "model", "bad-name"))

    assert commands == (
        ("gateway", "Gateway control commands and status"),
        ("help", "Show Codex help in the bound thread"),
        ("status", "Show Codex status in the bound thread"),
        ("model", "Switch or inspect the Codex model"),
        ("bad_name", "Pass through to the bound Codex thread"),
    )


def test_register_bot_commands_if_changed_skips_redundant_updates() -> None:
    from codex_telegram_gateway.config import GatewayConfig

    config = GatewayConfig(
        telegram_bot_token="test-token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
        telegram_menu_passthrough_commands=("help",),
    )
    state = DummyState()
    telegram = DummyTelegramClient()

    assert register_bot_commands_if_changed(telegram=telegram, state=state, config=config) is True
    assert register_bot_commands_if_changed(telegram=telegram, state=state, config=config) is False

    assert telegram.registered_command_sets == [
        (
            (
                ("gateway", "Gateway control commands and status"),
                ("help", "Show Codex help in the bound thread"),
            ),
            {"type": "chat", "chat_id": -100100},
        )
    ]
