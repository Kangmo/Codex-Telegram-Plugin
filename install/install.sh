#!/bin/sh

set -eu

REPO_URL="${CODEX_TELEGRAM_REPO_URL:-https://github.com/Kangmo/Codex-Telegram-Plugin}"
INSTALL_ROOT="${CODEX_TELEGRAM_INSTALL_ROOT:-$HOME/.codex-telegram-plugin}"
PYTHON_BIN="${PYTHON_BIN:-}"
VENV_PATH="$INSTALL_ROOT/.venv"
INSTALL_BOT_TOKEN="${CODEX_TELEGRAM_INSTALL_BOT_TOKEN:-}"
INSTALL_ALLOWED_USER_ID="${CODEX_TELEGRAM_INSTALL_ALLOWED_USER_ID:-}"
INSTALL_GROUP_CHAT_ID="${CODEX_TELEGRAM_INSTALL_GROUP_CHAT_ID:-}"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

python_is_compatible() {
  "$1" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)' \
    >/dev/null 2>&1
}

select_python() {
  if [ -n "$PYTHON_BIN" ]; then
    require_command "$PYTHON_BIN"
    if python_is_compatible "$PYTHON_BIN"; then
      return
    fi
    echo "Python 3.11 or newer is required: $PYTHON_BIN" >&2
    exit 1
  fi

  for candidate in python3.13 python3.12 python3.11 python3; do
    if ! command -v "$candidate" >/dev/null 2>&1; then
      continue
    fi
    if python_is_compatible "$candidate"; then
      PYTHON_BIN="$candidate"
      return
    fi
  done

  echo "Missing required command: python >= 3.11" >&2
  exit 1
}

run_install_command() {
  if [ -n "$INSTALL_BOT_TOKEN" ] || [ -n "$INSTALL_ALLOWED_USER_ID" ] || [ -n "$INSTALL_GROUP_CHAT_ID" ]; then
    if [ -z "$INSTALL_BOT_TOKEN" ] || [ -z "$INSTALL_ALLOWED_USER_ID" ] || [ -z "$INSTALL_GROUP_CHAT_ID" ]; then
      echo "Set CODEX_TELEGRAM_INSTALL_BOT_TOKEN, CODEX_TELEGRAM_INSTALL_ALLOWED_USER_ID, and CODEX_TELEGRAM_INSTALL_GROUP_CHAT_ID together." >&2
      exit 1
    fi
    "$VENV_PATH/bin/python" -m codex_telegram_gateway.cli install \
      --bot-token "$INSTALL_BOT_TOKEN" \
      --allowed-user-id "$INSTALL_ALLOWED_USER_ID" \
      --group-chat-id "$INSTALL_GROUP_CHAT_ID"
    return
  fi

  if [ -r /dev/tty ]; then
    "$VENV_PATH/bin/python" -m codex_telegram_gateway.cli install </dev/tty >/dev/tty
    return
  fi

  echo "Interactive install requires a terminal. Set CODEX_TELEGRAM_INSTALL_BOT_TOKEN, CODEX_TELEGRAM_INSTALL_ALLOWED_USER_ID, and CODEX_TELEGRAM_INSTALL_GROUP_CHAT_ID for non-interactive setup." >&2
  exit 1
}

require_command git
select_python

if [ -d "$INSTALL_ROOT/.git" ]; then
  git -C "$INSTALL_ROOT" pull --ff-only
else
  mkdir -p "$(dirname "$INSTALL_ROOT")"
  git clone "$REPO_URL" "$INSTALL_ROOT"
fi

"$PYTHON_BIN" -m venv "$VENV_PATH"
"$VENV_PATH/bin/python" -m pip install --upgrade pip
"$VENV_PATH/bin/python" -m pip install -e "$INSTALL_ROOT"
run_install_command
"$VENV_PATH/bin/python" -m codex_telegram_gateway.cli plugin install
