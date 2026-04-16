from codex_telegram_gateway.install_config import (
    InstallAnswers,
    build_managed_env,
    load_existing_env,
    parse_optional_int,
    prompt_install_answers,
    render_env_file,
)
from codex_telegram_gateway.runtime_paths import resolve_runtime_paths


def test_build_managed_env_merges_existing_optional_settings(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)

    values = build_managed_env(
        paths=paths,
        answers=InstallAnswers(
            telegram_bot_token="test-token",
            telegram_allowed_user_id=6013473151,
            telegram_default_chat_id=-5251936830,
        ),
        existing_env={
            "CODEX_TELEGRAM_WHISPER_PROVIDER": "openai",
        },
    )

    assert values == {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_ALLOWED_USER_IDS": "6013473151",
        "TELEGRAM_DEFAULT_CHAT_ID": "-5251936830",
        "CODEX_TELEGRAM_STATE_DB": str(tmp_path / ".codex-telegram" / "gateway.db"),
        "CODEX_TELEGRAM_TOOLBAR_CONFIG": str(tmp_path / ".codex-telegram" / "toolbar.toml"),
        "CODEX_TELEGRAM_WHISPER_PROVIDER": "openai",
    }


def test_render_env_file_orders_managed_keys_first(tmp_path) -> None:
    paths = resolve_runtime_paths(home=tmp_path)

    rendered = render_env_file(
        build_managed_env(
            paths=paths,
            answers=InstallAnswers(
                telegram_bot_token="test-token",
                telegram_allowed_user_id=6013473151,
                telegram_default_chat_id=-5251936830,
            ),
            existing_env={
                "CODEX_TELEGRAM_WHISPER_PROVIDER": "openai",
            },
        )
    )

    assert rendered == (
        "TELEGRAM_BOT_TOKEN=test-token\n"
        "TELEGRAM_ALLOWED_USER_IDS=6013473151\n"
        "TELEGRAM_DEFAULT_CHAT_ID=-5251936830\n"
        f"CODEX_TELEGRAM_STATE_DB={tmp_path / '.codex-telegram' / 'gateway.db'}\n"
        f"CODEX_TELEGRAM_TOOLBAR_CONFIG={tmp_path / '.codex-telegram' / 'toolbar.toml'}\n"
        "CODEX_TELEGRAM_WHISPER_PROVIDER=openai\n"
    )


def test_parse_optional_int_returns_existing_value_for_blank_text() -> None:
    assert parse_optional_int("", existing_value=6013473151) == 6013473151


def test_parse_optional_int_rejects_non_numeric_text() -> None:
    try:
        parse_optional_int("abc", existing_value=6013473151)
    except ValueError as exc:
        assert str(exc) == "Expected an integer value, got: abc"
    else:
        raise AssertionError("parse_optional_int accepted non-numeric text")


def test_parse_optional_int_rejects_blank_text_without_existing_value() -> None:
    try:
        parse_optional_int("", existing_value=None)
    except ValueError as exc:
        assert str(exc) == "Expected an integer value, got: "
    else:
        raise AssertionError("parse_optional_int accepted blank text without a fallback")


def test_load_existing_env_ignores_comments_and_blank_lines(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "\n".join(
            [
                "# comment",
                "",
                "TELEGRAM_BOT_TOKEN=test-token",
                "TELEGRAM_ALLOWED_USER_IDS=6013473151",
            ]
        )
        + "\n"
    )

    assert load_existing_env(env_file) == {
        "TELEGRAM_BOT_TOKEN": "test-token",
        "TELEGRAM_ALLOWED_USER_IDS": "6013473151",
    }


def test_load_existing_env_rejects_invalid_line(tmp_path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("INVALID\n")

    try:
        load_existing_env(env_file)
    except ValueError as exc:
        assert str(exc) == "Invalid .env line: INVALID"
    else:
        raise AssertionError("load_existing_env accepted an invalid line")


def test_prompt_install_answers_requires_token_for_first_install() -> None:
    try:
        prompt_install_answers(
            existing_env={},
            input_func=lambda _prompt="": "6013473151",
            secret_input_func=lambda _prompt="": "",
        )
    except ValueError as exc:
        assert str(exc) == "Telegram bot token is required"
    else:
        raise AssertionError("prompt_install_answers accepted a missing token")


def test_render_env_file_skips_missing_managed_keys() -> None:
    assert render_env_file({"CODEX_TELEGRAM_WHISPER_PROVIDER": "openai"}) == (
        "CODEX_TELEGRAM_WHISPER_PROVIDER=openai\n"
    )


def test_prompt_install_answers_uses_non_interactive_overrides_without_prompting() -> None:
    answers = prompt_install_answers(
        existing_env={},
        bot_token_override="test-token",
        allowed_user_id_override=6013473151,
        group_chat_id_override=-5251936830,
        input_func=lambda _prompt="": (_ for _ in ()).throw(AssertionError("unexpected prompt")),
        secret_input_func=lambda _prompt="": (_ for _ in ()).throw(AssertionError("unexpected prompt")),
    )

    assert answers == InstallAnswers(
        telegram_bot_token="test-token",
        telegram_allowed_user_id=6013473151,
        telegram_default_chat_id=-5251936830,
    )
