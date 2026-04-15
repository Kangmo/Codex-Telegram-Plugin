from codex_telegram_gateway.remote_actions import (
    RemoteActionContext,
    RemotePromptOption,
    build_remote_action_rows,
    parse_remote_action_callback,
)


def test_build_remote_action_rows_for_running_turn_exposes_stop_and_continue() -> None:
    rows = build_remote_action_rows(
        RemoteActionContext(
            state="running",
            turn_id="turn-1",
            supports_interrupt=True,
            supports_continue=True,
        )
    )

    assert rows == (
        (
            {"text": "⏹ Stop", "callback_data": "gw:remote:interrupt:turn-1"},
            {"text": "▶ Continue", "callback_data": "gw:remote:continue:turn-1"},
        ),
    )


def test_build_remote_action_rows_for_failed_turn_exposes_retry_last() -> None:
    rows = build_remote_action_rows(
        RemoteActionContext(
            state="failed",
            history_count=1,
            supports_retry=True,
        )
    )

    assert rows == (
        (
            {"text": "↻ Retry Last", "callback_data": "gw:remote:retry:0"},
        ),
    )


def test_build_remote_action_rows_for_approval_prompt_exposes_choices() -> None:
    rows = build_remote_action_rows(
        RemoteActionContext(
            state="approval",
            prompt_id="prompt-1",
            prompt_options=(
                RemotePromptOption(option_id="accept", label="Approve Once"),
                RemotePromptOption(option_id="cancel", label="Cancel Turn"),
            ),
            supports_prompt_choices=True,
        )
    )

    assert rows == (
        (
            {
                "text": "Approve Once",
                "callback_data": "gw:remote:prompt:prompt-1:accept",
            },
        ),
        (
            {
                "text": "Cancel Turn",
                "callback_data": "gw:remote:prompt:prompt-1:cancel",
            },
        ),
    )


def test_parse_remote_action_callback_understands_supported_actions() -> None:
    assert parse_remote_action_callback("gw:remote:interrupt:turn-1") == {
        "action": "interrupt",
        "turn_id": "turn-1",
    }
    assert parse_remote_action_callback("gw:remote:continue:turn-1") == {
        "action": "continue",
        "turn_id": "turn-1",
    }
    assert parse_remote_action_callback("gw:remote:retry:0") == {
        "action": "retry",
        "history_index": "0",
    }
    assert parse_remote_action_callback("gw:remote:prompt:prompt-1:accept") == {
        "action": "prompt",
        "prompt_id": "prompt-1",
        "choice": "accept",
    }
    assert parse_remote_action_callback("gw:remote:broken") is None
