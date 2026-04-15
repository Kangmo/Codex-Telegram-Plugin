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


def test_gateway_config_loads_lifecycle_intervals_from_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_USER_IDS=111",
                "TELEGRAM_DEFAULT_CHAT_ID=-100100",
                "TELEGRAM_LIFECYCLE_PROBE_INTERVAL_SECONDS=12.5",
                "TELEGRAM_LIFECYCLE_UNBOUND_TTL_SECONDS=34.5",
                "TELEGRAM_LIFECYCLE_AUTOCLOSE_AFTER_SECONDS=56.5",
                "TELEGRAM_LIFECYCLE_PRUNE_INTERVAL_SECONDS=78.5",
            ]
        )
    )

    config = GatewayConfig.from_env(env_file)

    assert config.lifecycle_probe_interval_seconds == 12.5
    assert config.lifecycle_unbound_ttl_seconds == 34.5
    assert config.lifecycle_autoclose_after_seconds == 56.5
    assert config.lifecycle_prune_interval_seconds == 78.5


def test_gateway_config_loads_mirror_chat_ids_and_dedupes_targets(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_USER_IDS=111",
                "TELEGRAM_DEFAULT_CHAT_ID=-100100",
                "TELEGRAM_MIRROR_CHAT_IDS=-100200,-100100,-100300",
            ]
        )
    )

    config = GatewayConfig.from_env(env_file)

    assert config.telegram_mirror_chat_ids == (-100200, -100300)
    assert config.telegram_target_chat_ids == (-100100, -100200, -100300)


def test_gateway_config_loads_menu_passthrough_commands_from_env_file(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_USER_IDS=111",
                "TELEGRAM_DEFAULT_CHAT_ID=-100100",
                "CODEX_TELEGRAM_MENU_PASSTHROUGH_COMMANDS=help,status,model",
            ]
        )
    )

    config = GatewayConfig.from_env(env_file)

    assert config.telegram_menu_passthrough_commands == ("help", "status", "model")
