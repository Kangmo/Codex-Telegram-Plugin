from pathlib import Path

from codex_telegram_gateway.config import GatewayConfig


def test_gateway_config_loads_from_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_USER_IDS=111,222",
                "TELEGRAM_DEFAULT_CHAT_ID=-100100",
                "CODEX_TELEGRAM_STATE_DB=.codex-telegram/test.db",
            ]
        )
    )

    config = GatewayConfig.from_env(env_file)

    assert config.telegram_bot_token == "test-token"
    assert config.telegram_allowed_user_ids == {111, 222}
    assert config.telegram_default_chat_id == -100100
    assert config.state_database_path == Path(".codex-telegram/test.db")
    assert config.telegram_topic_status_emoji_enabled is True


def test_gateway_config_loads_topic_status_emoji_toggle_from_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_USER_IDS=111",
                "TELEGRAM_DEFAULT_CHAT_ID=-100100",
                "TELEGRAM_TOPIC_STATUS_EMOJI_ENABLED=false",
            ]
        )
    )

    config = GatewayConfig.from_env(env_file)

    assert config.telegram_topic_status_emoji_enabled is False
