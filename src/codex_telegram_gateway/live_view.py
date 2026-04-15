from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path


CALLBACK_LIVE_VIEW_PREFIX = "gw:live:"
_KNOWN_ACTIONS = frozenset({"refresh", "stop", "start"})


@dataclass(frozen=True)
class LiveViewState:
    chat_id: int
    message_thread_id: int
    message_id: int
    codex_thread_id: str
    project_id: str | None
    started_at: float
    next_refresh_at: float = 0.0
    last_capture_hash: str = ""


def build_live_view_markup(*, active: bool = True) -> dict[str, object]:
    if active:
        return {
            "inline_keyboard": [
                [
                    {"text": "Refresh", "callback_data": f"{CALLBACK_LIVE_VIEW_PREFIX}refresh"},
                    {"text": "Stop", "callback_data": f"{CALLBACK_LIVE_VIEW_PREFIX}stop"},
                ]
            ]
        }
    return {
        "inline_keyboard": [
            [
                {"text": "Start live", "callback_data": f"{CALLBACK_LIVE_VIEW_PREFIX}start"},
            ]
        ]
    }


def parse_live_view_callback(data: str) -> str | None:
    if not data.startswith(CALLBACK_LIVE_VIEW_PREFIX):
        return None
    action = data[len(CALLBACK_LIVE_VIEW_PREFIX) :].strip()
    if action not in _KNOWN_ACTIONS:
        return None
    return action


def render_live_view_caption(*, project_name: str, thread_title: str) -> str:
    return f"Live view · {project_name} / {thread_title}"


def capture_hash_for_path(file_path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(file_path.read_bytes())
    return digest.hexdigest()
