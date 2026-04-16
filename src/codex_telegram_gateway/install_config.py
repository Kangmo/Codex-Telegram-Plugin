from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from codex_telegram_gateway.runtime_paths import RuntimePaths


@dataclass(frozen=True)
class InstallAnswers:
    """Interactive install or reconfigure answers."""

    telegram_bot_token: str
    telegram_allowed_user_id: int
    telegram_default_chat_id: int


def load_existing_env(env_file: Path) -> dict[str, str]:
    """Load an existing managed env file if present."""
    if not env_file.is_file():
        return {}
    values: dict[str, str] = {}
    for raw_line in env_file.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid .env line: {raw_line}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def parse_optional_int(raw_text: str, *, existing_value: int | None = None) -> int:
    """Parse an operator-provided integer value with blank-text fallback."""
    normalized = raw_text.strip()
    if normalized == "":
        if existing_value is None:
            raise ValueError("Expected an integer value, got: ")
        return existing_value
    try:
        return int(normalized)
    except ValueError as exc:
        raise ValueError(f"Expected an integer value, got: {raw_text}") from exc


def build_managed_env(
    *,
    paths: RuntimePaths,
    answers: InstallAnswers,
    existing_env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build the managed environment payload for install or reconfigure."""
    values = dict(existing_env or {})
    values.update(
        {
            "TELEGRAM_BOT_TOKEN": answers.telegram_bot_token,
            "TELEGRAM_ALLOWED_USER_IDS": str(answers.telegram_allowed_user_id),
            "TELEGRAM_DEFAULT_CHAT_ID": str(answers.telegram_default_chat_id),
            "CODEX_TELEGRAM_STATE_DB": str(paths.state_database_path),
            "CODEX_TELEGRAM_TOOLBAR_CONFIG": str(paths.toolbar_config_path),
        }
    )
    return values


def render_env_file(values: Mapping[str, str]) -> str:
    """Render the managed environment payload to `.env` text."""
    managed_order = [
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_ALLOWED_USER_IDS",
        "TELEGRAM_DEFAULT_CHAT_ID",
        "CODEX_TELEGRAM_STATE_DB",
        "CODEX_TELEGRAM_TOOLBAR_CONFIG",
    ]
    lines: list[str] = []
    emitted: set[str] = set()
    for key in managed_order:
        if key not in values:
            continue
        lines.append(f"{key}={values[key]}")
        emitted.add(key)
    for key in sorted(values):
        if key in emitted:
            continue
        lines.append(f"{key}={values[key]}")
    return "".join(f"{line}\n" for line in lines)


def write_env_file(env_file: Path, values: Mapping[str, str]) -> None:
    """Write the managed environment payload to disk."""
    env_file.parent.mkdir(parents=True, exist_ok=True)
    env_file.write_text(render_env_file(values))


def prompt_install_answers(
    *,
    existing_env: Mapping[str, str] | None = None,
    bot_token_override: str | None = None,
    allowed_user_id_override: int | None = None,
    group_chat_id_override: int | None = None,
    input_func=input,
    secret_input_func=input,
) -> InstallAnswers:
    """Collect interactive install or reconfigure values."""
    existing = dict(existing_env or {})
    token = _resolve_secret_value(
        bot_token_override,
        label="Telegram bot token",
        existing_value=existing.get("TELEGRAM_BOT_TOKEN"),
        secret_input_func=secret_input_func,
    )
    allowed_user_id = _resolve_optional_int(
        allowed_user_id_override,
        label="Numeric allowed Telegram user ID",
        existing_value=_maybe_int(existing.get("TELEGRAM_ALLOWED_USER_IDS")),
        input_func=input_func,
    )
    if group_chat_id_override is None:
        group_chat_id = _resolve_optional_int(
            None,
            label="Telegram group chat ID",
            existing_value=_maybe_int(existing.get("TELEGRAM_DEFAULT_CHAT_ID")),
            input_func=input_func,
        )
    else:
        group_chat_id = group_chat_id_override
    return InstallAnswers(
        telegram_bot_token=token,
        telegram_allowed_user_id=allowed_user_id,
        telegram_default_chat_id=group_chat_id,
    )


def _prompt_secret(
    label: str,
    *,
    existing_value: str | None,
    secret_input_func,
) -> str:
    raw_value = secret_input_func(_prompt_with_default(label, existing_value, show_value=False))
    normalized = raw_value.strip()
    if normalized:
        return normalized
    if existing_value:
        return existing_value
    raise ValueError(f"{label} is required")


def _resolve_secret_value(
    override_value: str | None,
    *,
    label: str,
    existing_value: str | None,
    secret_input_func,
) -> str:
    if override_value is not None:
        normalized = override_value.strip()
        if normalized:
            return normalized
        if existing_value:
            return existing_value
        raise ValueError(f"{label} is required")
    return _prompt_secret(
        label,
        existing_value=existing_value,
        secret_input_func=secret_input_func,
    )


def _resolve_optional_int(
    override_value: int | None,
    *,
    label: str,
    existing_value: int | None,
    input_func,
) -> int:
    if override_value is not None:
        return override_value
    return parse_optional_int(
        input_func(_prompt_with_default(label, _stringify_optional_int(existing_value))),
        existing_value=existing_value,
    )


def _prompt_with_default(
    label: str,
    existing_value: str | None,
    *,
    show_value: bool = True,
) -> str:
    if existing_value is None or existing_value == "":
        return f"{label}: "
    if show_value:
        return f"{label} [{existing_value}]: "
    return f"{label} [press Enter to keep current value]: "


def _maybe_int(raw_value: str | None) -> int | None:
    if raw_value is None or raw_value.strip() == "":
        return None
    return int(raw_value)


def _stringify_optional_int(value: int | None) -> str | None:
    if value is None:
        return None
    return str(value)
