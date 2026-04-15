import json
from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.shell_mode import (
    CALLBACK_SHELL_CANCEL,
    CALLBACK_SHELL_RUN,
    LocalSubprocessShellRunner,
    ShellCommandSuggestion,
    ShellExecutionResult,
    ShellSuggestionView,
    build_shell_command_suggester,
    parse_shell_callback,
    parse_shell_request,
    render_shell_help,
    render_shell_result,
    render_shell_suggestion,
)


class DummyShellCommandSuggester:
    def suggest_command(
        self,
        *,
        description: str,
        cwd: str,
        project_name: str,
        thread_title: str,
    ) -> ShellCommandSuggestion:
        assert description == "list python files"
        assert cwd == "/tmp/project"
        assert project_name == "project"
        assert thread_title == "thread"
        return ShellCommandSuggestion(
            command="find . -name '*.py'",
            explanation="List Python files in the current working tree.",
            original_text=description,
        )


class DummyShellRunner:
    def run(
        self,
        *,
        command: str,
        cwd: str,
        timeout_seconds: float,
    ) -> ShellExecutionResult:
        assert command == "find . -name '*.py'"
        assert cwd == "/tmp/project"
        assert timeout_seconds == 30.0
        return ShellExecutionResult(
            command=command,
            cwd=cwd,
            exit_code=0,
            stdout="./src/main.py\n./tests/test_main.py\n",
        )


def test_parse_shell_request_distinguishes_help_raw_and_suggest_modes() -> None:
    assert parse_shell_request("") == __import__(
        "codex_telegram_gateway.shell_mode",
        fromlist=["ShellRequest"],
    ).ShellRequest(mode="help", payload="")
    assert parse_shell_request("!pwd") == __import__(
        "codex_telegram_gateway.shell_mode",
        fromlist=["ShellRequest"],
    ).ShellRequest(mode="raw", payload="pwd")
    assert parse_shell_request("list python files") == __import__(
        "codex_telegram_gateway.shell_mode",
        fromlist=["ShellRequest"],
    ).ShellRequest(mode="suggest", payload="list python files")


def test_parse_shell_callback_recognizes_run_and_cancel_actions() -> None:
    assert parse_shell_callback(CALLBACK_SHELL_RUN) == "run"
    assert parse_shell_callback(CALLBACK_SHELL_CANCEL) == "cancel"
    assert parse_shell_callback("gw:shell:unknown") is None


def test_render_shell_help_documents_raw_and_natural_language_usage() -> None:
    assert render_shell_help() == "\n".join(
        [
            "Shell command mode",
            "",
            "/gateway shell !<command> - Run a raw shell command in the bound project directory",
            "/gateway shell <request> - Ask for a suggested shell command and approve it before running",
            "/gateway shell - Show this help",
        ]
    )


def test_render_shell_suggestion_uses_dummy_suggester_output() -> None:
    suggester = DummyShellCommandSuggester()
    suggestion = suggester.suggest_command(
        description="list python files",
        cwd="/tmp/project",
        project_name="project",
        thread_title="thread",
    )

    text, reply_markup = render_shell_suggestion(
        ShellSuggestionView(
            chat_id=-100100,
            message_thread_id=77,
            message_id=9,
            codex_thread_id="thread-1",
            cwd="/tmp/project",
            project_name="project",
            thread_title="thread",
            suggestion=suggestion,
        )
    )

    assert text == (
        "Shell command suggestion\n\n"
        "Request: `list python files`\n"
        "Project: `project`\n"
        "Thread: `thread`\n\n"
        "Suggested command:\n"
        "`find . -name '*.py'`\n\n"
        "List Python files in the current working tree."
    )
    assert reply_markup == {
        "inline_keyboard": [
            [{"text": "Run", "callback_data": CALLBACK_SHELL_RUN}],
            [{"text": "Cancel", "callback_data": CALLBACK_SHELL_CANCEL}],
        ]
    }


def test_render_shell_result_formats_dummy_runner_output() -> None:
    runner = DummyShellRunner()
    result = runner.run(
        command="find . -name '*.py'",
        cwd="/tmp/project",
        timeout_seconds=30.0,
    )

    assert render_shell_result(result, project_name="project") == (
        "Shell command result\n\n"
        "Command: `find . -name '*.py'`\n"
        "Project: `project`\n"
        "Exit code: `0`\n\n"
        "Stdout:\n"
        "```text\n"
        "./src/main.py\n"
        "./tests/test_main.py\n"
        "```"
    )


def test_build_shell_command_suggester_supports_defaults_and_validation() -> None:
    assert build_shell_command_suggester(
        GatewayConfig(
            telegram_bot_token="token",
            telegram_allowed_user_ids={111},
            telegram_default_chat_id=-100100,
            sync_mode="assistant_plus_alerts",
        )
    ) is None

    config = GatewayConfig(
        telegram_bot_token="token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
        shell_suggester_provider="openai",
        shell_suggester_api_key="test-key",
        shell_suggester_model="gpt-test",
    )
    provider = build_shell_command_suggester(config)
    assert provider is not None
    assert provider._base_url == "https://api.openai.com/v1"
    assert provider._model == "gpt-test"


def test_openai_compatible_shell_command_suggester_posts_completion_request(monkeypatch) -> None:
    shell_mode = __import__(
        "codex_telegram_gateway.shell_mode",
        fromlist=["build_shell_command_suggester"],
    )
    captured: dict[str, object] = {}

    class DummyResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            del exc_type, exc, tb

        def read(self) -> bytes:
            return json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": json.dumps(
                                    {
                                        "command": "find . -name '*.py'",
                                        "explanation": "List Python files in the current working tree.",
                                        "isDangerous": False,
                                    }
                                )
                            }
                        }
                    ]
                }
            ).encode()

    def fake_urlopen(req, timeout: float):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        captured["headers"] = dict(req.header_items())
        captured["payload"] = json.loads(req.data.decode())
        return DummyResponse()

    monkeypatch.setattr(shell_mode.request, "urlopen", fake_urlopen)
    provider = shell_mode.OpenAICompatibleShellCommandSuggester(
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model="gpt-test",
    )

    suggestion = provider.suggest_command(
        description="list python files",
        cwd="/tmp/project",
        project_name="project",
        thread_title="thread",
    )

    assert suggestion == ShellCommandSuggestion(
        command="find . -name '*.py'",
        explanation="List Python files in the current working tree.",
        original_text="list python files",
        is_dangerous=False,
    )
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["timeout"] == 60
    assert captured["headers"]["Authorization"] == "Bearer test-key"
    assert captured["payload"]["model"] == "gpt-test"
    assert captured["payload"]["response_format"] == {"type": "json_object"}


def test_local_subprocess_shell_runner_executes_command_in_cwd(tmp_path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    runner = LocalSubprocessShellRunner()

    result = runner.run(
        command="pwd",
        cwd=str(project_root),
        timeout_seconds=30.0,
    )

    assert result.command == "pwd"
    assert result.cwd == str(project_root)
    assert result.exit_code == 0
    assert result.stdout.strip() == str(project_root)
    assert result.stderr == ""
    assert result.timed_out is False
