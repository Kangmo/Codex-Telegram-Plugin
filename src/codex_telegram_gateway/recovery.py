from dataclasses import dataclass


RESTORE_ISSUE_CLOSED = "closed"
RESTORE_ISSUE_DELETED = "deleted"

CALLBACK_RESTORE_PREFIX = "gw:restore:"
CALLBACK_RESTORE_CONTINUE = f"{CALLBACK_RESTORE_PREFIX}continue"
CALLBACK_RESTORE_RECREATE = f"{CALLBACK_RESTORE_PREFIX}recreate"
CALLBACK_RESTORE_RESUME = f"{CALLBACK_RESTORE_PREFIX}resume"
CALLBACK_RESTORE_CANCEL = f"{CALLBACK_RESTORE_PREFIX}cancel"


@dataclass(frozen=True)
class RestorePrompt:
    text: str
    reply_markup: dict[str, object]


def render_restore_prompt(*, issue_kind: str, topic_name: str, thread_id: str) -> RestorePrompt:
    if issue_kind == RESTORE_ISSUE_CLOSED:
        text = (
            "Recovery options\n\n"
            f"Topic: `{topic_name}`\n"
            f"Thread id: `{thread_id}`\n\n"
            "This topic is currently marked closed, so new messages are not being routed to Codex.\n"
            "Choose how to restore it."
        )
        keyboard = [
            [
                {"text": "Continue Here", "callback_data": CALLBACK_RESTORE_CONTINUE},
                {"text": "Resume Other Thread", "callback_data": CALLBACK_RESTORE_RESUME},
            ],
            [{"text": "Cancel", "callback_data": CALLBACK_RESTORE_CANCEL}],
        ]
        return RestorePrompt(text=text, reply_markup={"inline_keyboard": keyboard})

    text = (
        "Recovery options\n\n"
        f"Topic: `{topic_name}`\n"
        f"Thread id: `{thread_id}`\n\n"
        "This binding points to a Telegram topic that was marked deleted or unreachable.\n"
        "Choose how to recover it."
    )
    keyboard = [
        [
            {"text": "Recreate Topic", "callback_data": CALLBACK_RESTORE_RECREATE},
            {"text": "Resume Other Thread", "callback_data": CALLBACK_RESTORE_RESUME},
        ],
        [{"text": "Cancel", "callback_data": CALLBACK_RESTORE_CANCEL}],
    ]
    return RestorePrompt(text=text, reply_markup={"inline_keyboard": keyboard})
