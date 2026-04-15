from codex_telegram_gateway.recovery import (
    CALLBACK_RESTORE_CANCEL,
    CALLBACK_RESTORE_CONTINUE,
    CALLBACK_RESTORE_RECREATE,
    CALLBACK_RESTORE_RESUME,
    RESTORE_ISSUE_CLOSED,
    RESTORE_ISSUE_DELETED,
    render_restore_prompt,
)


def test_render_restore_prompt_for_closed_topic() -> None:
    prompt = render_restore_prompt(
        issue_kind=RESTORE_ISSUE_CLOSED,
        topic_name="(gateway-project) thread-1",
        thread_id="thread-1",
    )

    assert "marked closed" in prompt.text
    assert prompt.reply_markup == {
        "inline_keyboard": [
            [
                {"text": "Continue Here", "callback_data": CALLBACK_RESTORE_CONTINUE},
                {"text": "Resume Other Thread", "callback_data": CALLBACK_RESTORE_RESUME},
            ],
            [{"text": "Cancel", "callback_data": CALLBACK_RESTORE_CANCEL}],
        ]
    }


def test_render_restore_prompt_for_deleted_topic() -> None:
    prompt = render_restore_prompt(
        issue_kind=RESTORE_ISSUE_DELETED,
        topic_name="(gateway-project) thread-1",
        thread_id="thread-1",
    )

    assert "marked deleted or unreachable" in prompt.text
    assert prompt.reply_markup == {
        "inline_keyboard": [
            [
                {"text": "Recreate Topic", "callback_data": CALLBACK_RESTORE_RECREATE},
                {"text": "Resume Other Thread", "callback_data": CALLBACK_RESTORE_RESUME},
            ],
            [{"text": "Cancel", "callback_data": CALLBACK_RESTORE_CANCEL}],
        ]
    }
