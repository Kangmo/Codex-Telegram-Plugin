from pathlib import Path

from codex_telegram_gateway.toolbar import (
    CALLBACK_TOOLBAR_PREFIX,
    build_toolbar_markup,
    load_toolbar_config,
    parse_toolbar_callback,
    render_toolbar_text,
)


def test_load_toolbar_config_uses_built_in_defaults() -> None:
    config = load_toolbar_config(None)

    layout = config.layout_for(
        chat_id=-100100,
        message_thread_id=77,
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )

    assert layout.style == "emoji_text"
    assert layout.buttons == (
        ("status", "history", "sync"),
        ("new", "project", "send"),
        ("compact", "steer", "close"),
    )
    assert config.actions["status"].action_type == "gateway_command"
    assert config.actions["compact"].action_type == "thread_text"
    assert config.actions["steer"].action_type == "steer_template"
    assert config.actions["close"].action_type == "builtin"


def test_load_toolbar_config_applies_project_and_topic_overrides_from_toml(tmp_path) -> None:
    config_path = tmp_path / "toolbar.toml"
    config_path.write_text(
        "\n".join(
            [
                '[actions.review]',
                'emoji = "🧪"',
                'text = "Review"',
                'type = "thread_text"',
                'payload = "/review"',
                "",
                "[layout]",
                'style = "text"',
                'buttons = [["status", "review"]]',
                "",
                '[projects."/Users/kangmo/sacle/src/gateway-project"]',
                'style = "emoji"',
                'buttons = [["review"]]',
                "",
                '[topics."-100100:77"]',
                'style = "emoji_text"',
                'buttons = [["sync", "review"], ["refresh"]]',
            ]
        )
    )

    config = load_toolbar_config(config_path)

    assert config.layout_for(
        chat_id=-100100,
        message_thread_id=77,
        project_id="/Users/kangmo/sacle/src/gateway-project",
    ).buttons == (("sync", "review"), ("refresh",))
    assert config.layout_for(
        chat_id=-100100,
        message_thread_id=88,
        project_id="/Users/kangmo/sacle/src/gateway-project",
    ).style == "emoji"
    assert config.layout_for(
        chat_id=-100100,
        message_thread_id=99,
        project_id="/Users/kangmo/sacle/src/other-project",
    ).style == "text"


def test_build_toolbar_markup_uses_selected_layout_style() -> None:
    config = load_toolbar_config(None)

    markup = build_toolbar_markup(
        config,
        chat_id=-100100,
        message_thread_id=77,
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )

    assert markup == {
        "inline_keyboard": [
            [
                {"text": "📍 Status", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}status"},
                {"text": "🧾 History", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}history"},
                {"text": "🔄 Sync", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}sync"},
            ],
            [
                {"text": "↺ New", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}new"},
                {"text": "📁 Project", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}project"},
                {"text": "📤 Send", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}send"},
            ],
            [
                {"text": "🧹 Compact", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}compact"},
                {"text": "🧭 Steer", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}steer"},
                {"text": "✖ Close", "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}close"},
            ],
        ]
    }


def test_parse_toolbar_callback_returns_action_name() -> None:
    assert parse_toolbar_callback(f"{CALLBACK_TOOLBAR_PREFIX}status") == "status"
    assert parse_toolbar_callback("gw:toolbar:") is None
    assert parse_toolbar_callback("gw:resp:status") is None


def test_render_toolbar_text_includes_bound_context() -> None:
    assert render_toolbar_text(
        project_id="/Users/kangmo/sacle/src/gateway-project",
        codex_thread_id="thread-1",
    ) == "Topic toolbar\n\nProject: `gateway-project`\nThread id: `thread-1`"

    assert render_toolbar_text(project_id=None, codex_thread_id=None) == "Topic toolbar\n\nNo Codex thread is bound yet."
