NOTIFICATION_MODES: tuple[str, ...] = ("all", "important", "errors_only", "muted")
_LEGACY_MODE_ALIASES = {
    "assistant_plus_alerts": "all",
    "assistant_only": "important",
}
_MODE_LABELS = {
    "all": "Bell All",
    "important": "Mention Important",
    "errors_only": "Warning Errors Only",
    "muted": "Silent Muted",
}
_MODE_DESCRIPTIONS = {
    "all": "typing and routine status chatter",
    "important": "only important alerts and errors",
    "errors_only": "only errors",
    "muted": "suppress supplemental chatter",
}
_VERBOSE_PREFIX = "gw:verbose:"


def normalize_notification_mode(mode: str) -> str:
    normalized = _LEGACY_MODE_ALIASES.get(mode.strip().lower(), mode.strip().lower())
    if normalized not in NOTIFICATION_MODES:
        raise ValueError(f"Invalid notification mode: {mode!r}")
    return normalized


def build_verbose_picker(mode: str) -> tuple[str, dict[str, object]]:
    current_mode = normalize_notification_mode(mode)
    text = (
        "Notification mode\n\n"
        f"Current: `{current_mode}`\n\n"
        f"- `all`: {_MODE_DESCRIPTIONS['all']}\n"
        f"- `important`: {_MODE_DESCRIPTIONS['important']}\n"
        f"- `errors_only`: {_MODE_DESCRIPTIONS['errors_only']}\n"
        f"- `muted`: {_MODE_DESCRIPTIONS['muted']}"
    )
    rows = [
        [
            {
                "text": notification_mode_button_text(option, selected=(option == current_mode)),
                "callback_data": f"{_VERBOSE_PREFIX}set:{option}",
            }
        ]
        for option in NOTIFICATION_MODES
    ]
    rows.append([{"text": "Dismiss", "callback_data": f"{_VERBOSE_PREFIX}dismiss"}])
    return text, {"inline_keyboard": rows}


def parse_verbose_callback(data: str) -> dict[str, str | None] | None:
    if not data.startswith(_VERBOSE_PREFIX):
        return None
    payload = data[len(_VERBOSE_PREFIX) :]
    if payload == "dismiss":
        return {"action": "dismiss", "mode": None}
    if not payload.startswith("set:"):
        return None
    raw_mode = payload[len("set:") :]
    try:
        mode = normalize_notification_mode(raw_mode)
    except ValueError:
        return None
    return {"action": "set", "mode": mode}


def should_emit_notification(mode: str, kind: str) -> bool:
    normalized_mode = normalize_notification_mode(mode)
    if kind == "error":
        return True
    if normalized_mode == "all":
        return kind in {"typing", "info", "important"}
    if normalized_mode == "important":
        return kind == "important"
    if normalized_mode in {"errors_only", "muted"}:
        return False
    raise ValueError(f"Invalid notification mode: {mode!r}")


def notification_mode_button_text(mode: str, *, selected: bool = False) -> str:
    normalized_mode = normalize_notification_mode(mode)
    label = _MODE_LABELS[normalized_mode]
    if selected:
        return f"✓ {label}"
    return label
