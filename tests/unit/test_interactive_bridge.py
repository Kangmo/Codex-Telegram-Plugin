from codex_telegram_gateway.interactive_bridge import (
    apply_interactive_callback,
    apply_interactive_text_answer,
    normalize_interactive_request,
    parse_interactive_callback,
    render_interactive_prompt,
    start_interactive_prompt_session,
)


def test_normalize_interactive_request_builds_command_approval_prompt() -> None:
    prompt = normalize_interactive_request(
        prompt_id="prompt-1",
        method="item/commandExecution/requestApproval",
        params={
            "threadId": "thread-1",
            "turnId": "turn-1",
            "itemId": "item-1",
            "command": "pytest -q",
            "cwd": "/tmp/project",
            "reason": "Run the test suite.",
        },
    )

    assert prompt is not None
    assert prompt.kind == "command_approval"
    assert prompt.thread_id == "thread-1"
    assert prompt.turn_id == "turn-1"
    assert prompt.title == "Command Approval"
    assert "pytest -q" in prompt.body
    assert "Run the test suite." in prompt.body
    assert [option.option_id for option in prompt.options] == [
        "accept",
        "acceptForSession",
        "decline",
        "cancel",
    ]


def test_tool_request_user_input_session_advances_and_returns_response_payload() -> None:
    prompt = normalize_interactive_request(
        prompt_id="prompt-2",
        method="item/tool/requestUserInput",
        params={
            "threadId": "thread-1",
            "turnId": "turn-2",
            "itemId": "item-2",
            "questions": [
                {
                    "header": "Mode",
                    "id": "mode",
                    "question": "Choose a mode",
                    "options": [
                        {"label": "Fast", "description": "Optimize for speed"},
                        {"label": "Safe", "description": "Optimize for caution"},
                    ],
                },
                {
                    "header": "Reason",
                    "id": "reason",
                    "question": "Why do you want this mode?",
                },
            ],
        },
    )

    assert prompt is not None
    session = start_interactive_prompt_session(prompt)

    first_text, first_markup = render_interactive_prompt(session)
    assert "Mode" in first_text
    assert "Choose a mode" in first_text
    assert first_markup is not None
    assert first_markup["inline_keyboard"][0][0]["text"] == "Fast"

    first_option_id = prompt.questions[0].options[0].option_id
    updated = apply_interactive_callback(session, action="choose", value=first_option_id)
    assert updated.response_payload is None

    second_text, second_markup = render_interactive_prompt(session)
    assert "Reason" in second_text
    assert "Why do you want this mode?" in second_text
    assert second_markup is None

    completed = apply_interactive_text_answer(session, "Need safer changes for production.")
    assert completed.response_payload == {
        "answers": {
            "mode": {"answers": ["Fast"]},
            "reason": {"answers": ["Need safer changes for production."]},
        }
    }


def test_parse_interactive_callback_understands_choice_and_other_actions() -> None:
    assert parse_interactive_callback("gw:prompt:choose:prompt-1:accept") == {
        "action": "choose",
        "prompt_id": "prompt-1",
        "value": "accept",
    }
    assert parse_interactive_callback("gw:prompt:other:prompt-2") == {
        "action": "other",
        "prompt_id": "prompt-2",
        "value": None,
    }
    assert parse_interactive_callback("gw:prompt:broken") is None
