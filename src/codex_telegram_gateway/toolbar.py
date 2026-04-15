from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib
from typing import Literal


ToolbarStyle = Literal["emoji", "text", "emoji_text"]
ToolbarActionType = Literal["gateway_command", "thread_text", "steer_template", "builtin"]

CALLBACK_TOOLBAR_PREFIX = "gw:toolbar:"

_VALID_STYLES = {"emoji", "text", "emoji_text"}
_VALID_ACTION_TYPES = {"gateway_command", "thread_text", "steer_template", "builtin"}


@dataclass(frozen=True)
class ToolbarAction:
    name: str
    emoji: str
    text: str
    action_type: ToolbarActionType
    payload: str

    def render(self, style: ToolbarStyle) -> str:
        if style == "emoji":
            return self.emoji or self.text
        if style == "text":
            return self.text or self.emoji
        if self.emoji and self.text:
            return f"{self.emoji} {self.text}"
        return self.emoji or self.text


@dataclass(frozen=True)
class ToolbarLayout:
    style: ToolbarStyle
    buttons: tuple[tuple[str, ...], ...]


@dataclass
class ToolbarConfig:
    default_layout: ToolbarLayout
    actions: dict[str, ToolbarAction] = field(default_factory=dict)
    project_layouts: dict[str, ToolbarLayout] = field(default_factory=dict)
    topic_layouts: dict[tuple[int, int], ToolbarLayout] = field(default_factory=dict)

    def layout_for(
        self,
        *,
        chat_id: int,
        message_thread_id: int,
        project_id: str | None,
    ) -> ToolbarLayout:
        topic_layout = self.topic_layouts.get((chat_id, message_thread_id))
        if topic_layout is not None:
            return topic_layout
        if project_id:
            project_layout = self.project_layouts.get(project_id)
            if project_layout is not None:
                return project_layout
        return self.default_layout


_DEFAULT_ACTIONS: dict[str, ToolbarAction] = {
    "status": ToolbarAction("status", "📍", "Status", "gateway_command", "status"),
    "history": ToolbarAction("history", "🧾", "History", "gateway_command", "history"),
    "sync": ToolbarAction("sync", "🔄", "Sync", "gateway_command", "sync"),
    "new": ToolbarAction("new", "↺", "New", "gateway_command", "create_thread"),
    "project": ToolbarAction("project", "📁", "Project", "gateway_command", "project"),
    "send": ToolbarAction("send", "📤", "Send", "gateway_command", "send"),
    "compact": ToolbarAction("compact", "🧹", "Compact", "thread_text", "/compact"),
    "steer": ToolbarAction(
        "steer",
        "🧭",
        "Steer",
        "steer_template",
        "Focus on the last user request and continue.",
    ),
    "close": ToolbarAction("close", "✖", "Close", "builtin", "dismiss"),
    "refresh": ToolbarAction("refresh", "↻", "Refresh", "builtin", "refresh"),
}

_DEFAULT_LAYOUT = ToolbarLayout(
    style="emoji_text",
    buttons=(
        ("status", "history", "sync"),
        ("new", "project", "send"),
        ("compact", "steer", "close"),
    ),
)


def load_toolbar_config(config_path: Path | None) -> ToolbarConfig:
    config = ToolbarConfig(
        default_layout=_DEFAULT_LAYOUT,
        actions=dict(_DEFAULT_ACTIONS),
        project_layouts={},
        topic_layouts={},
    )
    if config_path is None:
        return config
    resolved_path = Path(config_path)
    if not resolved_path.exists():
        return config

    raw_config = tomllib.loads(resolved_path.read_text(encoding="utf-8"))
    actions = raw_config.get("actions")
    if isinstance(actions, dict):
        for action_name, raw_action in actions.items():
            parsed_action = _parse_action(str(action_name), raw_action)
            if parsed_action is not None:
                config.actions[parsed_action.name] = parsed_action

    parsed_default_layout = _parse_layout(raw_config.get("layout"), fallback=_DEFAULT_LAYOUT)
    if parsed_default_layout is not None:
        config.default_layout = parsed_default_layout

    projects = raw_config.get("projects")
    if isinstance(projects, dict):
        for project_id, raw_layout in projects.items():
            parsed_layout = _parse_layout(raw_layout, fallback=config.default_layout)
            if parsed_layout is not None:
                config.project_layouts[str(project_id)] = parsed_layout

    topics = raw_config.get("topics")
    if isinstance(topics, dict):
        for topic_key, raw_layout in topics.items():
            parsed_topic = _parse_topic_key(str(topic_key))
            parsed_layout = _parse_layout(raw_layout, fallback=config.default_layout)
            if parsed_topic is None or parsed_layout is None:
                continue
            config.topic_layouts[parsed_topic] = parsed_layout
    return config


def build_toolbar_markup(
    config: ToolbarConfig,
    *,
    chat_id: int,
    message_thread_id: int,
    project_id: str | None,
) -> dict[str, object]:
    layout = config.layout_for(
        chat_id=chat_id,
        message_thread_id=message_thread_id,
        project_id=project_id,
    )
    keyboard: list[list[dict[str, str]]] = []
    for row_names in layout.buttons:
        row: list[dict[str, str]] = []
        for action_name in row_names:
            action = config.actions.get(action_name)
            if action is None:
                continue
            row.append(
                {
                    "text": action.render(layout.style),
                    "callback_data": f"{CALLBACK_TOOLBAR_PREFIX}{action.name}",
                }
            )
        if row:
            keyboard.append(row)
    return {"inline_keyboard": keyboard}


def render_toolbar_text(
    *,
    project_id: str | None,
    codex_thread_id: str | None,
) -> str:
    if not project_id and not codex_thread_id:
        return "Topic toolbar\n\nNo Codex thread is bound yet."

    lines = ["Topic toolbar", ""]
    if project_id:
        lines.append(f"Project: `{Path(project_id).name or project_id}`")
    if codex_thread_id:
        lines.append(f"Thread id: `{codex_thread_id}`")
    return "\n".join(lines)


def parse_toolbar_callback(data: str) -> str | None:
    if not data.startswith(CALLBACK_TOOLBAR_PREFIX):
        return None
    action_name = data[len(CALLBACK_TOOLBAR_PREFIX) :].strip()
    return action_name or None


def _parse_action(name: str, raw_action: object) -> ToolbarAction | None:
    if not isinstance(raw_action, dict):
        return None
    action_type = str(raw_action.get("type") or "").strip()
    if action_type not in _VALID_ACTION_TYPES:
        return None
    payload = str(raw_action.get("payload") or "").strip()
    if not payload:
        return None
    emoji = str(raw_action.get("emoji") or "").strip()
    text = str(raw_action.get("text") or "").strip()
    if not emoji and not text:
        return None
    return ToolbarAction(
        name=name,
        emoji=emoji,
        text=text,
        action_type=action_type,  # type: ignore[arg-type]
        payload=payload,
    )


def _parse_layout(raw_layout: object, *, fallback: ToolbarLayout) -> ToolbarLayout | None:
    if raw_layout is None:
        return fallback
    if not isinstance(raw_layout, dict):
        return None
    style = str(raw_layout.get("style") or fallback.style).strip()
    if style not in _VALID_STYLES:
        return None
    raw_buttons = raw_layout.get("buttons")
    if raw_buttons is None:
        buttons = fallback.buttons
    else:
        buttons = _normalize_buttons(raw_buttons)
        if buttons is None:
            return None
    return ToolbarLayout(style=style, buttons=buttons)  # type: ignore[arg-type]


def _normalize_buttons(raw_buttons: object) -> tuple[tuple[str, ...], ...] | None:
    if not isinstance(raw_buttons, list):
        return None
    normalized_rows: list[tuple[str, ...]] = []
    for raw_row in raw_buttons:
        if not isinstance(raw_row, list):
            return None
        row = tuple(str(item).strip() for item in raw_row if str(item).strip())
        if row:
            normalized_rows.append(row)
    return tuple(normalized_rows)


def _parse_topic_key(raw_key: str) -> tuple[int, int] | None:
    chat_id_text, separator, thread_id_text = raw_key.partition(":")
    if not separator:
        return None
    try:
        return int(chat_id_text), int(thread_id_text)
    except ValueError:
        return None
