"""Telegram command menu generation for gateway and pass-through Codex commands."""

from __future__ import annotations

import hashlib
import json

from codex_telegram_gateway.config import GatewayConfig
from codex_telegram_gateway.ports import GatewayState, TelegramClient

_GATEWAY_COMMAND = ("gateway", "Gateway control commands and status")
_GENERIC_PASSTHROUGH_DESCRIPTION = "Pass through to the bound Codex thread"
_KNOWN_PASSTHROUGH_DESCRIPTIONS: dict[str, str] = {
    "help": "Show Codex help in the bound thread",
    "status": "Show Codex status in the bound thread",
    "model": "Switch or inspect the Codex model",
    "plan": "Switch Codex planning mode in the bound thread",
    "mcp": "List Codex MCP servers and tools",
    "tasks": "Manage Codex background tasks",
    "permissions": "Review Codex tool permissions",
    "memory": "Open Codex memory instructions",
    "init": "Initialize Codex project guidance",
    "clear": "Clear recent Codex thread context",
    "compact": "Compact Codex thread context",
    "effort": "Adjust Codex reasoning effort",
}
_MAX_TELEGRAM_COMMANDS = 100
_MAX_DESCRIPTION_LEN = 256


def build_bot_commands(
    config: GatewayConfig,
    *,
    observed_passthrough_commands: tuple[str, ...] = (),
) -> tuple[tuple[str, str], ...]:
    commands: list[tuple[str, str]] = [_GATEWAY_COMMAND]
    seen_names = {_GATEWAY_COMMAND[0]}
    for raw_name in (*config.telegram_menu_passthrough_commands, *observed_passthrough_commands):
        command_name = _sanitize_command_name(raw_name)
        if not command_name or command_name in seen_names:
            continue
        seen_names.add(command_name)
        commands.append(
            (
                command_name,
                _KNOWN_PASSTHROUGH_DESCRIPTIONS.get(command_name, _GENERIC_PASSTHROUGH_DESCRIPTION)[
                    :_MAX_DESCRIPTION_LEN
                ],
            )
        )
        if len(commands) >= _MAX_TELEGRAM_COMMANDS:
            break
    return tuple(commands)


def register_bot_commands_if_changed(
    *,
    telegram: TelegramClient,
    state: GatewayState,
    config: GatewayConfig,
) -> bool:
    commands = build_bot_commands(
        config,
        observed_passthrough_commands=state.list_passthrough_commands(),
    )
    scope = {"type": "chat", "chat_id": config.telegram_default_chat_id}
    scope_key = f"chat:{config.telegram_default_chat_id}"
    catalog_hash = hashlib.sha256(json.dumps(commands, separators=(",", ":")).encode("utf-8")).hexdigest()
    if state.get_registered_command_menu_hash(scope_key) == catalog_hash:
        return False
    telegram.set_my_commands(list(commands), scope=scope)
    state.set_registered_command_menu_hash(scope_key, catalog_hash)
    return True


def _sanitize_command_name(command_name: str) -> str:
    normalized = command_name.strip().lstrip("/").lower()
    sanitized = normalized.replace("-", "_")
    sanitized = "".join(character for character in sanitized if character.isalnum() or character == "_")
    return sanitized[:32]
