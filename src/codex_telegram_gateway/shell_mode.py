import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol
from urllib import error, request

from codex_telegram_gateway.config import GatewayConfig


CALLBACK_SHELL_PREFIX = "gw:shell:"
CALLBACK_SHELL_RUN = f"{CALLBACK_SHELL_PREFIX}run"
CALLBACK_SHELL_CANCEL = f"{CALLBACK_SHELL_PREFIX}cancel"


@dataclass(frozen=True)
class ShellRequest:
    mode: Literal["help", "raw", "suggest"]
    payload: str = ""


@dataclass(frozen=True)
class ShellCommandSuggestion:
    command: str
    explanation: str
    original_text: str
    is_dangerous: bool = False


@dataclass(frozen=True)
class ShellExecutionResult:
    command: str
    cwd: str
    exit_code: int
    stdout: str = ""
    stderr: str = ""
    timed_out: bool = False


@dataclass(frozen=True)
class ShellSuggestionView:
    chat_id: int
    message_thread_id: int
    message_id: int
    codex_thread_id: str
    cwd: str
    project_name: str
    thread_title: str
    suggestion: ShellCommandSuggestion


class ShellCommandSuggester(Protocol):
    def suggest_command(
        self,
        *,
        description: str,
        cwd: str,
        project_name: str,
        thread_title: str,
    ) -> ShellCommandSuggestion:
        ...


class ShellRunner(Protocol):
    def run(
        self,
        *,
        command: str,
        cwd: str,
        timeout_seconds: float,
    ) -> ShellExecutionResult:
        ...


class OpenAICompatibleShellCommandSuggester:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
    ) -> None:
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self._model = model

    def suggest_command(
        self,
        *,
        description: str,
        cwd: str,
        project_name: str,
        thread_title: str,
    ) -> ShellCommandSuggestion:
        payload = {
            "model": self._model,
            "temperature": 0,
            "response_format": {"type": "json_object"},
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You translate a natural-language request into exactly one macOS zsh command. "
                        "Return strict JSON with keys command, explanation, and isDangerous. "
                        "Do not wrap the JSON in markdown. Prefer read-only commands unless the user "
                        "explicitly asks to modify files or system state."
                    ),
                },
                {
                    "role": "user",
                    "content": "\n".join(
                        [
                            f"Project: {project_name}",
                            f"Thread: {thread_title}",
                            f"Working directory: {cwd}",
                            f"Request: {description}",
                        ]
                    ),
                },
            ],
        }
        req = request.Request(
            f"{self._base_url}/chat/completions",
            data=json.dumps(payload).encode(),
            method="POST",
        )
        req.headers["Authorization"] = f"Bearer {self._api_key}"
        req.headers["Content-Type"] = "application/json"
        try:
            with request.urlopen(req, timeout=60) as response:
                response_payload = json.loads(response.read().decode())
        except error.HTTPError as exc:
            body_text = exc.read().decode()
            raise RuntimeError(f"Shell command suggestion failed: {body_text}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Shell command suggestion request failed: {exc}") from exc

        choices = response_payload.get("choices")
        if not isinstance(choices, list) or not choices:
            raise RuntimeError("Shell command suggestion returned no choices.")
        message = choices[0].get("message") if isinstance(choices[0], dict) else None
        raw_content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(raw_content, str) or not raw_content.strip():
            raise RuntimeError("Shell command suggestion returned no content.")
        try:
            content = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Shell command suggestion returned invalid JSON.") from exc
        command = str(content.get("command") or "").strip()
        if not command:
            raise RuntimeError("Shell command suggestion returned no command.")
        explanation = str(content.get("explanation") or "").strip()
        is_dangerous = bool(content.get("isDangerous") or content.get("is_dangerous"))
        return ShellCommandSuggestion(
            command=command,
            explanation=explanation,
            original_text=description,
            is_dangerous=is_dangerous,
        )


class LocalSubprocessShellRunner:
    def __init__(self, *, shell_executable: Path | str = "/bin/zsh") -> None:
        self._shell_executable = str(shell_executable)

    def run(
        self,
        *,
        command: str,
        cwd: str,
        timeout_seconds: float,
    ) -> ShellExecutionResult:
        try:
            completed = subprocess.run(
                [self._shell_executable, "-lc", command],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            return ShellExecutionResult(
                command=command,
                cwd=cwd,
                exit_code=124,
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
                timed_out=True,
            )
        return ShellExecutionResult(
            command=command,
            cwd=cwd,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            timed_out=False,
        )


def build_shell_command_suggester(config: GatewayConfig) -> ShellCommandSuggester | None:
    provider_name = config.shell_suggester_provider.strip().lower()
    if not provider_name:
        return None
    provider_defaults = _SHELL_SUGGESTER_PROVIDER_DEFAULTS.get(provider_name)
    if provider_defaults is None:
        raise ValueError(f"Unknown shell suggester provider: {provider_name}")
    api_key = config.shell_suggester_api_key.strip()
    if not api_key:
        raise ValueError("Missing shell suggester API key.")
    base_url = config.shell_suggester_base_url.strip() or provider_defaults["base_url"]
    model = config.shell_suggester_model.strip()
    if not model:
        raise ValueError("Missing shell suggester model.")
    return OpenAICompatibleShellCommandSuggester(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )


def build_shell_runner() -> ShellRunner:
    return LocalSubprocessShellRunner()


def parse_shell_request(command_args: str) -> ShellRequest:
    normalized = command_args.strip()
    if not normalized:
        return ShellRequest(mode="help", payload="")
    if normalized.startswith("!"):
        payload = normalized[1:].lstrip()
        if not payload:
            return ShellRequest(mode="help", payload="")
        return ShellRequest(mode="raw", payload=payload)
    return ShellRequest(mode="suggest", payload=normalized)


def parse_shell_callback(data: str) -> Literal["run", "cancel"] | None:
    if data == CALLBACK_SHELL_RUN:
        return "run"
    if data == CALLBACK_SHELL_CANCEL:
        return "cancel"
    return None


def render_shell_help() -> str:
    return "\n".join(
        [
            "Shell command mode",
            "",
            "/gateway shell !<command> - Run a raw shell command in the bound project directory",
            "/gateway shell <request> - Ask for a suggested shell command and approve it before running",
            "/gateway shell - Show this help",
        ]
    )


def render_shell_suggestion(view: ShellSuggestionView) -> tuple[str, dict[str, object]]:
    lines = [
        "Shell command suggestion",
        "",
        f"Request: `{view.suggestion.original_text}`",
        f"Project: `{view.project_name}`",
        f"Thread: `{view.thread_title}`",
        "",
        "Suggested command:",
        f"`{view.suggestion.command}`",
    ]
    if view.suggestion.explanation:
        lines.extend(["", view.suggestion.explanation])
    if view.suggestion.is_dangerous:
        lines.extend(["", "Warning: this command may modify files or system state."])
    return (
        "\n".join(lines),
        {
            "inline_keyboard": [
                [{"text": "Run", "callback_data": CALLBACK_SHELL_RUN}],
                [{"text": "Cancel", "callback_data": CALLBACK_SHELL_CANCEL}],
            ]
        },
    )


def render_shell_result(result: ShellExecutionResult, *, project_name: str) -> str:
    lines = [
        "Shell command result",
        "",
        f"Command: `{result.command}`",
        f"Project: `{project_name}`",
        f"Exit code: `{result.exit_code}`",
    ]
    if result.timed_out:
        lines.append("Timed out: `yes`")
    if result.stdout.strip():
        lines.extend(["", "Stdout:", "```text", result.stdout.rstrip(), "```"])
    if result.stderr.strip():
        lines.extend(["", "Stderr:", "```text", result.stderr.rstrip(), "```"])
    if not result.stdout.strip() and not result.stderr.strip():
        lines.extend(["", "(no output)"])
    return "\n".join(lines)


_SHELL_SUGGESTER_PROVIDER_DEFAULTS = {
    "openai": {"base_url": "https://api.openai.com/v1"},
    "groq": {"base_url": "https://api.groq.com/openai/v1"},
}
