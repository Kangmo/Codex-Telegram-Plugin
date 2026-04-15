from dataclasses import dataclass


CALLBACK_REMOTE_ACTION_PREFIX = "gw:remote:"
_CALLBACK_REMOTE_INTERRUPT_PREFIX = f"{CALLBACK_REMOTE_ACTION_PREFIX}interrupt:"
_CALLBACK_REMOTE_CONTINUE_PREFIX = f"{CALLBACK_REMOTE_ACTION_PREFIX}continue:"
_CALLBACK_REMOTE_RETRY_PREFIX = f"{CALLBACK_REMOTE_ACTION_PREFIX}retry:"
_CALLBACK_REMOTE_PROMPT_PREFIX = f"{CALLBACK_REMOTE_ACTION_PREFIX}prompt:"


@dataclass(frozen=True)
class RemotePromptOption:
    option_id: str
    label: str


@dataclass(frozen=True)
class RemoteActionContext:
    state: str
    turn_id: str | None = None
    history_count: int = 0
    prompt_id: str | None = None
    prompt_options: tuple[RemotePromptOption, ...] = ()
    supports_interrupt: bool = False
    supports_continue: bool = False
    supports_retry: bool = False
    supports_prompt_choices: bool = False


def build_remote_action_rows(
    context: RemoteActionContext,
) -> tuple[tuple[dict[str, str], ...], ...]:
    rows: list[tuple[dict[str, str], ...]] = []
    if context.state == "running" and context.turn_id:
        buttons: list[dict[str, str]] = []
        if context.supports_interrupt:
            buttons.append(
                {
                    "text": "⏹ Stop",
                    "callback_data": f"{_CALLBACK_REMOTE_INTERRUPT_PREFIX}{context.turn_id}",
                }
            )
        if context.supports_continue:
            buttons.append(
                {
                    "text": "▶ Continue",
                    "callback_data": f"{_CALLBACK_REMOTE_CONTINUE_PREFIX}{context.turn_id}",
                }
            )
        if buttons:
            rows.append(tuple(buttons))
        return tuple(rows)
    if (
        context.state == "approval"
        and context.prompt_id
        and context.prompt_options
        and context.supports_prompt_choices
    ):
        for option in context.prompt_options:
            rows.append(
                (
                    {
                        "text": option.label,
                        "callback_data": f"{_CALLBACK_REMOTE_PROMPT_PREFIX}{context.prompt_id}:{option.option_id}",
                    },
                )
            )
        return tuple(rows)
    if context.state == "failed" and context.history_count > 0 and context.supports_retry:
        rows.append(
            (
                {
                    "text": "↻ Retry Last",
                    "callback_data": f"{_CALLBACK_REMOTE_RETRY_PREFIX}0",
                },
            )
        )
    return tuple(rows)


def parse_remote_action_callback(data: str) -> dict[str, str] | None:
    if data.startswith(_CALLBACK_REMOTE_INTERRUPT_PREFIX):
        turn_id = data[len(_CALLBACK_REMOTE_INTERRUPT_PREFIX):]
        if not turn_id:
            return None
        return {"action": "interrupt", "turn_id": turn_id}
    if data.startswith(_CALLBACK_REMOTE_CONTINUE_PREFIX):
        turn_id = data[len(_CALLBACK_REMOTE_CONTINUE_PREFIX):]
        if not turn_id:
            return None
        return {"action": "continue", "turn_id": turn_id}
    if data.startswith(_CALLBACK_REMOTE_RETRY_PREFIX):
        history_index = data[len(_CALLBACK_REMOTE_RETRY_PREFIX):]
        if not history_index:
            return None
        return {"action": "retry", "history_index": history_index}
    if data.startswith(_CALLBACK_REMOTE_PROMPT_PREFIX):
        remainder = data[len(_CALLBACK_REMOTE_PROMPT_PREFIX):]
        prompt_id, separator, choice = remainder.rpartition(":")
        if not separator or not prompt_id or not choice:
            return None
        return {"action": "prompt", "prompt_id": prompt_id, "choice": choice}
    return None
