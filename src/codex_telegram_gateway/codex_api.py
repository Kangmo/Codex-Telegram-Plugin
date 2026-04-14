import json
import os
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from itertools import count
from pathlib import Path

from codex_telegram_gateway.app_store import (
    ensure_sidebar_workspace_root,
    thread_rollout_path,
)
from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.models import (
    CodexEvent,
    CodexProject,
    CodexThread,
    StartedTurn,
    TurnResult,
)


class CodexAppServerError(RuntimeError):
    """Raised when the Codex app server rejects a request."""


@dataclass(frozen=True)
class _JsonRpcResponse:
    request_id: int
    result: dict[str, object]


class CodexAppServerClient:
    """Minimal JSON-RPC client for the local Codex app-server stdio transport."""

    def __init__(self, config: GatewayConfig) -> None:
        self._config = config
        self._command = config.codex_app_server_command
        self._codex_home = Path.home() / ".codex"
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._request_ids = count(1)
        self._initialize()

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            self._process.wait(timeout=5)

    def __enter__(self) -> "CodexAppServerClient":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def get_current_thread_id(self) -> str:
        thread_id = os.environ.get("CODEX_THREAD_ID")
        if not thread_id:
            raise CodexAppServerError("CODEX_THREAD_ID is not set in the current shell.")
        return thread_id

    def list_loaded_threads(self) -> list[CodexThread]:
        thread_ids: list[str] = []
        seen_thread_ids: set[str] = set()
        cursor: str | None = None
        while True:
            response = self._request("thread/loaded/list", {"cursor": cursor, "limit": 100})
            for thread_id in response["data"]:
                normalized_thread_id = str(thread_id)
                if normalized_thread_id in seen_thread_ids:
                    continue
                seen_thread_ids.add(normalized_thread_id)
                thread_ids.append(normalized_thread_id)
            cursor_value = response.get("nextCursor")
            if cursor_value is None:
                break
            cursor = str(cursor_value)
        return [self.read_thread(thread_id) for thread_id in thread_ids]

    def list_loaded_projects(self) -> list[CodexProject]:
        projects_by_id: dict[str, CodexProject] = {}
        for thread in self.list_loaded_threads():
            if not thread.cwd:
                continue
            projects_by_id.setdefault(
                thread.cwd,
                CodexProject(
                    project_id=thread.cwd,
                    project_name=_project_name(thread.cwd),
                ),
            )
        return sorted(projects_by_id.values(), key=lambda project: (project.project_name, project.project_id))

    def list_all_threads(self) -> list[CodexThread]:
        raise CodexAppServerError(
            "Historical thread/list discovery is disabled. Use list_loaded_threads() "
            "from the Codex app context."
        )

    def list_workspace_threads(self, cwd: str) -> list[CodexThread]:
        raise CodexAppServerError(
            "Workspace history discovery is disabled. Use list_loaded_threads() "
            "from the Codex app context."
        )

    def read_thread(self, thread_id: str) -> CodexThread:
        response = self._request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": False},
        )
        thread = response["thread"]
        return CodexThread(
            thread_id=str(thread["id"]),
            title=_thread_title(thread),
            status=_thread_status(thread),
            cwd=str(thread.get("cwd") or ""),
        )

    def list_events(self, thread_id: str) -> list[CodexEvent]:
        response = self._request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
        )
        thread = response["thread"]
        events: list[CodexEvent] = []
        for turn in thread["turns"]:
            turn_id = str(turn["id"])
            for item in turn["items"]:
                if item.get("type") != "agentMessage":
                    continue
                if item.get("phase") == "commentary":
                    continue
                event_id = f"{thread_id}:{turn_id}:{item['id']}"
                events.append(
                    CodexEvent(
                        event_id=event_id,
                        thread_id=thread_id,
                        kind="assistant_message",
                        text=str(item["text"]),
                    )
                )
        return events

    def create_thread(self, project_id: str, thread_name: str | None = None) -> CodexThread:
        self.ensure_project_visible(project_id)
        response = self._request("thread/start", {"cwd": project_id})
        thread = response["thread"]
        created_thread = CodexThread(
            thread_id=str(thread["id"]),
            title=_thread_title(thread),
            status=_thread_status(thread),
            cwd=str(response.get("cwd") or thread.get("cwd") or project_id),
        )
        if thread_name:
            self._request(
                "thread/name/set",
                {
                    "threadId": created_thread.thread_id,
                    "name": thread_name,
                },
            )
            return self.read_thread(created_thread.thread_id)
        return created_thread

    def ensure_project_visible(self, project_id: str) -> None:
        ensure_sidebar_workspace_root(self._codex_home, project_id)

    def start_turn(
        self,
        started_turn: StartedTurn,
        on_progress: Callable[[], None] | None = None,
    ) -> TurnResult:
        thread = self.read_thread(started_turn.thread_id)
        if thread.status == "notLoaded":
            self._request("thread/resume", {"threadId": started_turn.thread_id})
        response = self._request(
            "turn/start",
            {
                "threadId": started_turn.thread_id,
                "input": _build_turn_input(started_turn),
            },
        )
        turn_id = str(response["turn"]["id"])
        if on_progress is not None:
            on_progress()
        return TurnResult(turn_id=turn_id, status="in_progress")

    def steer_turn(
        self,
        started_turn: StartedTurn,
        expected_turn_id: str,
        on_progress: Callable[[], None] | None = None,
    ) -> TurnResult:
        response = self._request(
            "turn/steer",
            {
                "threadId": started_turn.thread_id,
                "expectedTurnId": expected_turn_id,
                "input": _build_turn_input(started_turn),
            },
        )
        turn_id = str(response.get("turnId") or expected_turn_id)
        if on_progress is not None:
            on_progress()
        return TurnResult(turn_id=turn_id, status="in_progress")

    def inspect_turn(
        self,
        thread_id: str,
        turn_id: str,
        *,
        status: str | None = None,
    ) -> TurnResult:
        turn_status = status or self._read_turn_status(thread_id, turn_id)
        waiting_for_approval = False
        if turn_status == "interrupted":
            waiting_for_approval = _turn_waits_for_approval(self._codex_home, thread_id, turn_id)
        return TurnResult(
            turn_id=turn_id,
            status=turn_status,
            waiting_for_approval=waiting_for_approval,
        )

    def _initialize(self) -> None:
        self._request(
            "initialize",
            {
                "clientInfo": {
                    "name": "codex-telegram-gateway",
                    "title": "Codex Telegram Gateway",
                    "version": "0.1.0",
                },
                "capabilities": {"experimentalApi": True},
            },
        )
        self._notify("initialized")

    def _notify(self, method: str, params: dict[str, object] | None = None) -> None:
        message: dict[str, object] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self._write_message(message)

    def _request(self, method: str, params: dict[str, object]) -> dict[str, object]:
        request_id = next(self._request_ids)
        self._write_message(
            {
                "jsonrpc": "2.0",
                "id": request_id,
                "method": method,
                "params": params,
            }
        )
        while True:
            message = self._read_message()
            if "id" not in message:
                continue
            if int(message["id"]) != request_id:
                continue
            if "error" in message:
                raise CodexAppServerError(json.dumps(message["error"], sort_keys=True))
            result = message.get("result")
            if not isinstance(result, dict):
                raise CodexAppServerError(f"Malformed response for {method}: {message}")
            return result

    def _write_message(self, message: dict[str, object]) -> None:
        if self._process.stdin is None:
            raise CodexAppServerError("Codex app-server stdin is unavailable.")
        self._process.stdin.write(json.dumps(message) + "\n")
        self._process.stdin.flush()

    def _read_message(self) -> dict[str, object]:
        if self._process.stdout is None:
            raise CodexAppServerError("Codex app-server stdout is unavailable.")
        line = self._process.stdout.readline()
        if not line:
            stderr_output = ""
            if self._process.stderr is not None:
                stderr_output = self._process.stderr.read().strip()
            raise CodexAppServerError(
                f"Codex app-server closed unexpectedly. stderr={stderr_output}"
            )
        return json.loads(line)

    def _wait_for_turn_completion(
        self,
        thread_id: str,
        turn_id: str,
        timeout_seconds: int = 180,
        on_progress: Callable[[], None] | None = None,
        progress_interval_seconds: float = 4.0,
    ) -> str:
        deadline = time.time() + timeout_seconds
        last_progress_sent_at = 0.0
        with CodexAppServerClient(self._config) as waiter:
            while time.time() < deadline:
                now = time.time()
                if on_progress is not None and now - last_progress_sent_at >= progress_interval_seconds:
                    on_progress()
                    last_progress_sent_at = now
                response = waiter._request(
                    "thread/read",
                    {"threadId": thread_id, "includeTurns": True},
                )
                status = _matching_turn_status(response, turn_id)
                if status in {"completed", "failed", "interrupted"}:
                    return status
                time.sleep(1)
        raise CodexAppServerError(f"Timed out waiting for turn completion: {turn_id}")

    def _read_turn_status(self, thread_id: str, turn_id: str) -> str:
        response = self._request(
            "thread/read",
            {"threadId": thread_id, "includeTurns": True},
        )
        status = _matching_turn_status(response, turn_id)
        if not status:
            raise CodexAppServerError(f"Turn not found in thread/read: {turn_id}")
        return status


def _thread_title(thread: dict[str, object]) -> str:
    name = thread.get("name")
    if isinstance(name, str) and name.strip():
        return _normalize_topic_name(name)
    preview = thread.get("preview")
    if isinstance(preview, str) and preview.strip():
        return _normalize_topic_name(preview)
    return str(thread["id"])


def _thread_status(thread: dict[str, object]) -> str:
    status = thread.get("status")
    if isinstance(status, dict) and "type" in status:
        return str(status["type"])
    return str(status)


def _project_name(cwd: str) -> str:
    name = Path(cwd).name.strip()
    return name or cwd


def _build_turn_input(started_turn: StartedTurn) -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    for local_image_path in started_turn.local_image_paths:
        items.append({"type": "localImage", "path": local_image_path})
    if started_turn.text:
        items.append({"type": "text", "text": started_turn.text})
    return items


def _normalize_topic_name(text: str, limit: int = 96) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"


def _matching_turn_status(response: dict[str, object], turn_id: str) -> str:
    thread = response.get("thread")
    if not isinstance(thread, dict):
        return ""
    turns = thread.get("turns")
    if not isinstance(turns, list):
        return ""
    matching_turns = [turn for turn in turns if isinstance(turn, dict) and str(turn.get("id")) == turn_id]
    if not matching_turns:
        return ""
    return str(matching_turns[-1].get("status") or "")


def _turn_waits_for_approval(codex_home: Path, thread_id: str, turn_id: str) -> bool:
    rollout_path = thread_rollout_path(codex_home, thread_id)
    if rollout_path is None or not rollout_path.exists():
        return False

    turn_entries = _turn_session_entries(rollout_path, turn_id)
    if not turn_entries:
        return False

    approval_policy_on_request = False
    for entry in turn_entries:
        if not isinstance(entry, dict):
            continue
        entry_type = entry.get("type")
        payload = entry.get("payload")
        if not isinstance(payload, dict):
            continue
        if entry_type == "turn_context":
            approval_policy_on_request = payload.get("approval_policy") == "on-request"
            continue
        if entry_type != "response_item" or payload.get("type") != "function_call":
            continue
        arguments = payload.get("arguments")
        if not isinstance(arguments, str):
            continue
        try:
            parsed_arguments = json.loads(arguments)
        except json.JSONDecodeError:
            continue
        if (
            isinstance(parsed_arguments, dict)
            and parsed_arguments.get("sandbox_permissions") == "require_escalated"
            and approval_policy_on_request
        ):
            return True
    return False


def _turn_session_entries(rollout_path: Path, turn_id: str) -> list[dict[str, object]]:
    entries: list[dict[str, object]] = []
    capture = False
    for raw_line in rollout_path.read_text().splitlines():
        try:
            entry = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if _is_task_started(entry, turn_id):
            capture = True
            entries.append(entry)
            continue
        if capture and _is_task_started(entry, None):
            break
        if capture:
            entries.append(entry)
    return entries


def _is_task_started(entry: dict[str, object], turn_id: str | None) -> bool:
    payload = entry.get("payload")
    if entry.get("type") != "event_msg" or not isinstance(payload, dict):
        return False
    if payload.get("type") != "task_started":
        return False
    if turn_id is None:
        return True
    return str(payload.get("turn_id")) == turn_id
