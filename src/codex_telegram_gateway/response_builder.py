from __future__ import annotations

import re

from codex_telegram_gateway.models import CodexEvent

_COMMAND_ERROR_RE = re.compile(
    r"\b("
    r"error|failed|failure|exception|traceback|assertionerror|"
    r"permission denied|no such file|not found"
    r")\b",
    re.IGNORECASE,
)
_COMMAND_SUCCESS_RE = re.compile(
    r"\b("
    r"passed|success|successful|completed|ok"
    r")\b",
    re.IGNORECASE,
)


def build_outbound_events(
    thread_id: str,
    turns: list[dict[str, object]],
) -> list[CodexEvent]:
    """Normalize Codex App turn items into replayable Telegram-facing events."""
    events: list[CodexEvent] = []

    for turn in turns:
        turn_id = str(turn.get("id") or "turn")
        turn_status = str(turn.get("status") or "")
        raw_items = turn.get("items")
        if not isinstance(raw_items, list):
            continue

        command_items: list[dict[str, object]] = []
        all_command_items: list[dict[str, object]] = []
        batch_index = 0
        last_rendered_kind: str | None = None

        def flush_batch() -> None:
            nonlocal batch_index, last_rendered_kind
            if not command_items:
                return
            events.append(
                CodexEvent(
                    event_id=f"{thread_id}:{turn_id}:tool-batch:{batch_index}",
                    thread_id=thread_id,
                    kind="tool_batch",
                    text=_format_command_batch(command_items),
                )
            )
            last_rendered_kind = "tool_batch"
            batch_index += 1
            command_items.clear()

        for raw_item in raw_items:
            if not isinstance(raw_item, dict):
                continue
            item_type = str(raw_item.get("type") or "")

            if item_type == "commandExecution":
                command_items.append(raw_item)
                all_command_items.append(raw_item)
                continue

            flush_batch()

            if item_type != "agentMessage":
                continue
            if raw_item.get("phase") == "commentary":
                continue

            item_text = str(raw_item.get("text") or "").strip()
            if not item_text:
                continue

            item_id = str(raw_item.get("id") or "assistant")
            events.append(
                CodexEvent(
                    event_id=f"{thread_id}:{turn_id}:{item_id}",
                    thread_id=thread_id,
                    kind="assistant_message",
                    text=item_text,
                )
            )
            last_rendered_kind = "assistant_message"

        flush_batch()

        if last_rendered_kind == "assistant_message":
            continue
        if turn_status not in {"completed", "failed", "interrupted"}:
            continue

        summary_text = _completion_summary(turn_status, all_command_items)
        if not summary_text:
            continue
        events.append(
            CodexEvent(
                event_id=f"{thread_id}:{turn_id}:completion-summary",
                thread_id=thread_id,
                kind="completion_summary",
                text=summary_text,
            )
        )

    return events


def _format_command_batch(items: list[dict[str, object]]) -> str:
    count = len(items)
    label = "command" if count == 1 else "commands"
    lines = [f"⚡ {count} {label}"]
    lines.extend(_format_command_line(item) for item in items)
    return "\n".join(lines)


def _format_command_line(item: dict[str, object]) -> str:
    command = _command_label(item)
    state = _command_state(item)
    detail = _command_detail(item, state=state)
    icon = _command_state_icon(state)
    if detail:
        return f"• {command}  {icon} {detail}"
    return f"• {command}  {icon}"


def _completion_summary(turn_status: str, command_items: list[dict[str, object]]) -> str:
    suffix = ""
    if command_items:
        last_item = command_items[-1]
        command = _command_label(last_item)
        state = _command_state(last_item)
        detail = _command_detail(last_item, state=state)
        suffix = f"{command}: {detail}" if detail else command

    if turn_status == "completed":
        return f"✓ Done — {suffix}" if suffix else "✓ Done"
    if turn_status == "failed":
        return f"⚠ Turn failed — {suffix}" if suffix else "⚠ Turn failed"
    if turn_status == "interrupted":
        return f"⚠ Turn interrupted — {suffix}" if suffix else "⚠ Turn interrupted"
    return ""


def _command_state(item: dict[str, object]) -> str:
    exit_code = item.get("exitCode")
    if isinstance(exit_code, int):
        return "failed" if exit_code != 0 else "success"

    detail = _interesting_output_line(item.get("aggregatedOutput"))
    if detail:
        if _COMMAND_ERROR_RE.search(detail):
            return "failed"
        if _COMMAND_SUCCESS_RE.search(detail):
            return "success"

    return "running"


def _command_state_icon(state: str) -> str:
    if state == "failed":
        return "❌"
    if state == "success":
        return "✅"
    return "⏳"


def _command_detail(item: dict[str, object], *, state: str) -> str:
    detail = _interesting_output_line(item.get("aggregatedOutput"))
    if detail:
        return detail

    exit_code = item.get("exitCode")
    if isinstance(exit_code, int):
        return f"exit {exit_code}"

    if state == "running":
        return "running"
    return ""


def _command_label(item: dict[str, object], limit: int = 120) -> str:
    command = " ".join(str(item.get("command") or "command").split())
    if len(command) <= limit:
        return command
    return command[: limit - 1].rstrip() + "…"


def _interesting_output_line(raw_output: object, limit: int = 220) -> str:
    if not isinstance(raw_output, str):
        return ""

    non_empty_lines = [line.strip() for line in raw_output.splitlines() if line.strip()]
    if not non_empty_lines:
        return ""

    for line in non_empty_lines:
        lowered = line.lower()
        if any(token in lowered for token in ("assertionerror", "traceback", "exception", "permission denied")):
            return _trim(line, limit)
        if "warning" in lowered:
            return _trim(line, limit)

    for line in non_empty_lines:
        if _COMMAND_ERROR_RE.search(line):
            return _trim(line, limit)

    for line in non_empty_lines:
        if _COMMAND_SUCCESS_RE.search(line):
            return _trim(line, limit)

    return _trim(non_empty_lines[0], limit)


def _trim(text: str, limit: int) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 1].rstrip() + "…"
