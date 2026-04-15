from dataclasses import dataclass, field


_CALLBACK_PREFIX = "gw:prompt:"
_CALLBACK_CHOOSE_PREFIX = f"{_CALLBACK_PREFIX}choose:"
_CALLBACK_OTHER_PREFIX = f"{_CALLBACK_PREFIX}other:"


@dataclass(frozen=True)
class InteractivePromptOption:
    option_id: str
    label: str


@dataclass(frozen=True)
class InteractivePromptQuestion:
    question_id: str
    header: str
    question: str
    options: tuple[InteractivePromptOption, ...] = ()
    allow_other: bool = False
    is_secret: bool = False


@dataclass(frozen=True)
class InteractivePrompt:
    prompt_id: str
    thread_id: str
    turn_id: str | None
    kind: str
    title: str
    body: str
    options: tuple[InteractivePromptOption, ...] = ()
    questions: tuple[InteractivePromptQuestion, ...] = ()
    expires_on_restart: bool = True


@dataclass
class InteractivePromptSession:
    prompt: InteractivePrompt
    question_index: int = 0
    answers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    awaiting_text_question_id: str | None = None


@dataclass(frozen=True)
class InteractivePromptUpdate:
    session: InteractivePromptSession
    response_payload: dict[str, object] | None = None
    toast_text: str | None = None


def normalize_interactive_request(
    *,
    prompt_id: str,
    method: str,
    params: dict[str, object],
) -> InteractivePrompt | None:
    if method == "item/commandExecution/requestApproval":
        return InteractivePrompt(
            prompt_id=prompt_id,
            thread_id=str(params.get("threadId") or ""),
            turn_id=_string_or_none(params.get("turnId")),
            kind="command_approval",
            title="Command Approval",
            body=_command_approval_body(params),
            options=(
                InteractivePromptOption(option_id="accept", label="Approve Once"),
                InteractivePromptOption(option_id="acceptForSession", label="Approve Session"),
                InteractivePromptOption(option_id="decline", label="Decline"),
                InteractivePromptOption(option_id="cancel", label="Cancel Turn"),
            ),
        )
    if method == "item/fileChange/requestApproval":
        return InteractivePrompt(
            prompt_id=prompt_id,
            thread_id=str(params.get("threadId") or ""),
            turn_id=_string_or_none(params.get("turnId")),
            kind="file_change_approval",
            title="File Change Approval",
            body=_file_change_approval_body(params),
            options=(
                InteractivePromptOption(option_id="accept", label="Approve Once"),
                InteractivePromptOption(option_id="acceptForSession", label="Approve Session"),
                InteractivePromptOption(option_id="decline", label="Decline"),
                InteractivePromptOption(option_id="cancel", label="Cancel Turn"),
            ),
        )
    if method == "item/tool/requestUserInput":
        raw_questions = params.get("questions")
        if not isinstance(raw_questions, list):
            return None
        questions: list[InteractivePromptQuestion] = []
        for question_index, raw_question in enumerate(raw_questions):
            if not isinstance(raw_question, dict):
                continue
            raw_options = raw_question.get("options")
            options: list[InteractivePromptOption] = []
            if isinstance(raw_options, list):
                for option_index, raw_option in enumerate(raw_options):
                    if not isinstance(raw_option, dict):
                        continue
                    label = str(raw_option.get("label") or "").strip()
                    if not label:
                        continue
                    options.append(
                        InteractivePromptOption(
                            option_id=f"q{question_index}o{option_index}",
                            label=label,
                        )
                    )
            questions.append(
                InteractivePromptQuestion(
                    question_id=str(raw_question.get("id") or f"question-{question_index + 1}"),
                    header=str(raw_question.get("header") or f"Question {question_index + 1}"),
                    question=str(raw_question.get("question") or "").strip(),
                    options=tuple(options),
                    allow_other=bool(raw_question.get("isOther")),
                    is_secret=bool(raw_question.get("isSecret")),
                )
            )
        if not questions:
            return None
        return InteractivePrompt(
            prompt_id=prompt_id,
            thread_id=str(params.get("threadId") or ""),
            turn_id=_string_or_none(params.get("turnId")),
            kind="tool_request_user_input",
            title="Input Required",
            body="Codex needs an answer before it can continue.",
            questions=tuple(questions),
        )
    return None


def start_interactive_prompt_session(prompt: InteractivePrompt) -> InteractivePromptSession:
    return InteractivePromptSession(prompt=prompt)


def render_interactive_prompt(
    session: InteractivePromptSession,
) -> tuple[str, dict[str, object] | None]:
    prompt = session.prompt
    if prompt.kind in {"command_approval", "file_change_approval"}:
        text = prompt.title
        if prompt.body:
            text += f"\n\n{prompt.body}"
        return text, {
            "inline_keyboard": [
                [
                    {
                        "text": option.label,
                        "callback_data": f"{_CALLBACK_CHOOSE_PREFIX}{prompt.prompt_id}:{option.option_id}",
                    }
                ]
                for option in prompt.options
            ]
        }

    if prompt.kind != "tool_request_user_input" or not prompt.questions:
        return prompt.title, None

    question = prompt.questions[min(session.question_index, len(prompt.questions) - 1)]
    text_lines = [
        prompt.title,
        "",
        question.header,
        question.question,
    ]
    if question.is_secret:
        text_lines.extend(
            [
                "",
                "This answer must stay secret. Continue it from Codex App.",
            ]
        )
        return "\n".join(line for line in text_lines if line), None

    if session.awaiting_text_question_id == question.question_id or not question.options:
        text_lines.extend(
            [
                "",
                "Reply in Telegram with your answer.",
            ]
        )
        return "\n".join(line for line in text_lines if line), None

    rows = [
        [
            {
                "text": option.label,
                "callback_data": f"{_CALLBACK_CHOOSE_PREFIX}{prompt.prompt_id}:{option.option_id}",
            }
        ]
        for option in question.options
    ]
    if question.allow_other:
        rows.append(
            [
                {
                    "text": "Other",
                    "callback_data": f"{_CALLBACK_OTHER_PREFIX}{prompt.prompt_id}",
                }
            ]
        )
    return "\n".join(line for line in text_lines if line), {"inline_keyboard": rows}


def parse_interactive_callback(data: str) -> dict[str, str | None] | None:
    if data.startswith(_CALLBACK_CHOOSE_PREFIX):
        remainder = data[len(_CALLBACK_CHOOSE_PREFIX):]
        prompt_id, separator, value = remainder.rpartition(":")
        if not separator or not prompt_id or not value:
            return None
        return {"action": "choose", "prompt_id": prompt_id, "value": value}
    if data.startswith(_CALLBACK_OTHER_PREFIX):
        prompt_id = data[len(_CALLBACK_OTHER_PREFIX):]
        if not prompt_id:
            return None
        return {"action": "other", "prompt_id": prompt_id, "value": None}
    return None


def apply_interactive_callback(
    session: InteractivePromptSession,
    *,
    action: str,
    value: str | None,
) -> InteractivePromptUpdate:
    prompt = session.prompt
    if prompt.kind in {"command_approval", "file_change_approval"}:
        if action != "choose" or value is None:
            raise ValueError("Approval prompts require a choice.")
        if value not in {option.option_id for option in prompt.options}:
            raise ValueError("Unknown approval choice.")
        return InteractivePromptUpdate(
            session=session,
            response_payload={"decision": value},
            toast_text="Sent.",
        )

    if prompt.kind != "tool_request_user_input" or not prompt.questions:
        raise ValueError("Unsupported interactive prompt type.")

    question = prompt.questions[min(session.question_index, len(prompt.questions) - 1)]
    if action == "other":
        session.awaiting_text_question_id = question.question_id
        return InteractivePromptUpdate(session=session)
    if action != "choose" or value is None:
        raise ValueError("Invalid interactive prompt action.")

    selected = next((option for option in question.options if option.option_id == value), None)
    if selected is None:
        raise ValueError("Unknown interactive prompt option.")

    session.answers[question.question_id] = (selected.label,)
    session.awaiting_text_question_id = None
    session.question_index += 1
    return _tool_prompt_update(session)


def apply_interactive_text_answer(
    session: InteractivePromptSession,
    text: str,
) -> InteractivePromptUpdate:
    prompt = session.prompt
    if prompt.kind != "tool_request_user_input" or not prompt.questions:
        raise ValueError("This prompt does not accept text replies.")

    question = prompt.questions[min(session.question_index, len(prompt.questions) - 1)]
    if question.is_secret:
        raise ValueError("Secret questions must be answered elsewhere.")
    if question.options and session.awaiting_text_question_id != question.question_id:
        raise ValueError("This question expects a button choice.")
    normalized_text = text.strip()
    if not normalized_text:
        raise ValueError("Text answer cannot be empty.")
    session.answers[question.question_id] = (normalized_text,)
    session.awaiting_text_question_id = None
    session.question_index += 1
    return _tool_prompt_update(session)


def _command_approval_body(params: dict[str, object]) -> str:
    lines: list[str] = []
    command = _string_or_none(params.get("command"))
    cwd = _string_or_none(params.get("cwd"))
    reason = _string_or_none(params.get("reason"))
    if command:
        lines.append(f"Command: `{command}`")
    if cwd:
        lines.append(f"Directory: `{cwd}`")
    if reason:
        lines.append(reason)
    return "\n".join(lines)


def _file_change_approval_body(params: dict[str, object]) -> str:
    reason = _string_or_none(params.get("reason"))
    if reason:
        return reason
    return "Codex wants to apply file changes."


def _tool_prompt_update(session: InteractivePromptSession) -> InteractivePromptUpdate:
    if session.question_index < len(session.prompt.questions):
        return InteractivePromptUpdate(session=session)
    return InteractivePromptUpdate(
        session=session,
        response_payload={
            "answers": {
                question_id: {"answers": list(answer_values)}
                for question_id, answer_values in session.answers.items()
            }
        },
        toast_text="Sent.",
    )


def _string_or_none(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None
