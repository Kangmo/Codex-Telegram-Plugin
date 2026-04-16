#!/bin/sh

set -eu

REPO_URL="${CODEX_TELEGRAM_REPO_URL:-https://github.com/Kangmo/Codex-Telegram-Plugin}"
INSTALL_ROOT="${CODEX_TELEGRAM_INSTALL_ROOT:-$HOME/.codex-telegram-plugin}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_PATH="$INSTALL_ROOT/.venv"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_command git
require_command "$PYTHON_BIN"

if [ -d "$INSTALL_ROOT/.git" ]; then
  git -C "$INSTALL_ROOT" pull --ff-only
else
  mkdir -p "$(dirname "$INSTALL_ROOT")"
  git clone "$REPO_URL" "$INSTALL_ROOT"
fi

"$PYTHON_BIN" -m venv "$VENV_PATH"
"$VENV_PATH/bin/python" -m pip install --upgrade pip
"$VENV_PATH/bin/python" -m pip install -e "$INSTALL_ROOT"
"$VENV_PATH/bin/python" -m codex_telegram_gateway.cli install
"$VENV_PATH/bin/python" -m codex_telegram_gateway.cli plugin install
