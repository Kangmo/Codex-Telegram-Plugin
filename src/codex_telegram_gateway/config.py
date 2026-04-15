import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GatewayConfig:
    """Configuration required by the gateway runtime."""

    telegram_bot_token: str
    telegram_allowed_user_ids: set[int]
    telegram_default_chat_id: int
    sync_mode: str
    telegram_mirror_chat_ids: tuple[int, ...] = ()
    telegram_menu_passthrough_commands: tuple[str, ...] = ()
    telegram_topic_status_emoji_enabled: bool = True
    lifecycle_probe_interval_seconds: float = 60.0
    lifecycle_unbound_ttl_seconds: float = 1800.0
    lifecycle_autoclose_after_seconds: float = 0.0
    lifecycle_prune_interval_seconds: float = 300.0
    live_view_interval_seconds: float = 5.0
    live_view_timeout_seconds: float = 300.0
    shell_command_timeout_seconds: float = 30.0
    state_database_path: Path = Path(".codex-telegram/gateway.db")
    toolbar_config_path: Path = Path(".codex-telegram/toolbar.toml")
    codex_app_server_command: tuple[str, ...] = ("codex", "app-server", "--listen", "stdio://")
    shell_suggester_provider: str = ""
    shell_suggester_api_key: str = ""
    shell_suggester_base_url: str = ""
    shell_suggester_model: str = ""
    voice_transcription_provider: str = ""
    voice_transcription_api_key: str = ""
    voice_transcription_base_url: str = ""
    voice_transcription_model: str = ""
    voice_transcription_language: str = ""

    @classmethod
    def from_env(cls, env_path: Path | None = None) -> "GatewayConfig":
        """Load runtime configuration from process env and an optional .env file."""
        env = dict(os.environ)
        if env_path is not None:
            env.update(_read_env_file(env_path))

        bot_token = _require_env(env, "TELEGRAM_BOT_TOKEN")
        allowed_user_ids = {
            int(raw_user_id.strip())
            for raw_user_id in _require_env(env, "TELEGRAM_ALLOWED_USER_IDS").split(",")
            if raw_user_id.strip()
        }
        chat_id = int(_require_env(env, "TELEGRAM_DEFAULT_CHAT_ID"))
        mirror_chat_ids = tuple(
            int(raw_chat_id.strip())
            for raw_chat_id in env.get("TELEGRAM_MIRROR_CHAT_IDS", "").split(",")
            if raw_chat_id.strip()
        )
        menu_passthrough_commands = _env_command_list(
            env,
            "CODEX_TELEGRAM_MENU_PASSTHROUGH_COMMANDS",
        )
        state_database_path = Path(
            env.get("CODEX_TELEGRAM_STATE_DB", ".codex-telegram/gateway.db")
        )
        toolbar_config_path = Path(
            env.get("CODEX_TELEGRAM_TOOLBAR_CONFIG", ".codex-telegram/toolbar.toml")
        )
        sync_mode = env.get("TELEGRAM_SYNC_MODE", "assistant_plus_alerts")
        topic_status_emoji_enabled = _env_bool(
            env,
            "TELEGRAM_TOPIC_STATUS_EMOJI_ENABLED",
            default=True,
        )
        lifecycle_probe_interval_seconds = _env_float(
            env,
            "TELEGRAM_LIFECYCLE_PROBE_INTERVAL_SECONDS",
            default=60.0,
        )
        lifecycle_unbound_ttl_seconds = _env_float(
            env,
            "TELEGRAM_LIFECYCLE_UNBOUND_TTL_SECONDS",
            default=1800.0,
        )
        lifecycle_autoclose_after_seconds = _env_float(
            env,
            "TELEGRAM_LIFECYCLE_AUTOCLOSE_AFTER_SECONDS",
            default=0.0,
        )
        lifecycle_prune_interval_seconds = _env_float(
            env,
            "TELEGRAM_LIFECYCLE_PRUNE_INTERVAL_SECONDS",
            default=300.0,
        )
        live_view_interval_seconds = _env_float(
            env,
            "CODEX_TELEGRAM_LIVE_VIEW_INTERVAL_SECONDS",
            default=5.0,
        )
        live_view_timeout_seconds = _env_float(
            env,
            "CODEX_TELEGRAM_LIVE_VIEW_TIMEOUT_SECONDS",
            default=300.0,
        )
        shell_command_timeout_seconds = _env_float(
            env,
            "CODEX_TELEGRAM_SHELL_COMMAND_TIMEOUT_SECONDS",
            default=30.0,
        )
        shell_suggester_provider = env.get("CODEX_TELEGRAM_SHELL_SUGGESTER_PROVIDER", "").strip()
        shell_suggester_api_key = env.get("CODEX_TELEGRAM_SHELL_SUGGESTER_API_KEY", "").strip()
        shell_suggester_base_url = env.get("CODEX_TELEGRAM_SHELL_SUGGESTER_BASE_URL", "").strip()
        shell_suggester_model = env.get("CODEX_TELEGRAM_SHELL_SUGGESTER_MODEL", "").strip()
        voice_transcription_provider = env.get("CODEX_TELEGRAM_WHISPER_PROVIDER", "").strip()
        voice_transcription_api_key = env.get("CODEX_TELEGRAM_WHISPER_API_KEY", "").strip()
        voice_transcription_base_url = env.get("CODEX_TELEGRAM_WHISPER_BASE_URL", "").strip()
        voice_transcription_model = env.get("CODEX_TELEGRAM_WHISPER_MODEL", "").strip()
        voice_transcription_language = env.get("CODEX_TELEGRAM_WHISPER_LANGUAGE", "").strip()
        return cls(
            telegram_bot_token=bot_token,
            telegram_allowed_user_ids=allowed_user_ids,
            telegram_default_chat_id=chat_id,
            telegram_mirror_chat_ids=tuple(
                configured_chat_id
                for configured_chat_id in mirror_chat_ids
                if configured_chat_id != chat_id
            ),
            sync_mode=sync_mode,
            telegram_menu_passthrough_commands=menu_passthrough_commands,
            telegram_topic_status_emoji_enabled=topic_status_emoji_enabled,
            lifecycle_probe_interval_seconds=lifecycle_probe_interval_seconds,
            lifecycle_unbound_ttl_seconds=lifecycle_unbound_ttl_seconds,
            lifecycle_autoclose_after_seconds=lifecycle_autoclose_after_seconds,
            lifecycle_prune_interval_seconds=lifecycle_prune_interval_seconds,
            live_view_interval_seconds=live_view_interval_seconds,
            live_view_timeout_seconds=live_view_timeout_seconds,
            shell_command_timeout_seconds=shell_command_timeout_seconds,
            state_database_path=state_database_path,
            toolbar_config_path=toolbar_config_path,
            shell_suggester_provider=shell_suggester_provider,
            shell_suggester_api_key=shell_suggester_api_key,
            shell_suggester_base_url=shell_suggester_base_url,
            shell_suggester_model=shell_suggester_model,
            voice_transcription_provider=voice_transcription_provider,
            voice_transcription_api_key=voice_transcription_api_key,
            voice_transcription_base_url=voice_transcription_base_url,
            voice_transcription_model=voice_transcription_model,
            voice_transcription_language=voice_transcription_language,
        )

    @property
    def sync_lock_path(self) -> Path:
        return self.state_database_path.with_name("telegram-sync.lock")

    @property
    def telegram_target_chat_ids(self) -> tuple[int, ...]:
        seen_chat_ids: set[int] = set()
        ordered_chat_ids: list[int] = []
        for chat_id in (self.telegram_default_chat_id, *self.telegram_mirror_chat_ids):
            if chat_id in seen_chat_ids:
                continue
            seen_chat_ids.add(chat_id)
            ordered_chat_ids.append(chat_id)
        return tuple(ordered_chat_ids)


def _require_env(env: dict[str, str], name: str) -> str:
    value = env.get(name)
    if value is None or value == "":
        raise ValueError(f"Missing required configuration: {name}")
    return value


def _read_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}

    values: dict[str, str] = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"Invalid .env line: {raw_line}")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _env_bool(env: dict[str, str], name: str, *, default: bool) -> bool:
    value = env.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean configuration for {name}: {value}")


def _env_float(env: dict[str, str], name: str, *, default: float) -> float:
    value = env.get(name)
    if value is None:
        return default
    return float(value)


def _env_command_list(env: dict[str, str], name: str) -> tuple[str, ...]:
    raw_value = env.get(name, "")
    commands: list[str] = []
    seen: set[str] = set()
    for raw_command in raw_value.split(","):
        normalized = raw_command.strip().lstrip("/").lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        commands.append(normalized)
    return tuple(commands)
