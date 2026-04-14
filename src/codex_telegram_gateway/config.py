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
    state_database_path: Path = Path(".codex-telegram/gateway.db")
    codex_app_server_command: tuple[str, ...] = ("codex", "app-server", "--listen", "stdio://")

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
        state_database_path = Path(
            env.get("CODEX_TELEGRAM_STATE_DB", ".codex-telegram/gateway.db")
        )
        sync_mode = env.get("TELEGRAM_SYNC_MODE", "assistant_plus_alerts")
        return cls(
            telegram_bot_token=bot_token,
            telegram_allowed_user_ids=allowed_user_ids,
            telegram_default_chat_id=chat_id,
            sync_mode=sync_mode,
            state_database_path=state_database_path,
        )

    @property
    def sync_lock_path(self) -> Path:
        return self.state_database_path.with_name("telegram-sync.lock")


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
