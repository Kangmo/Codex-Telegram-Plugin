#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${REPO_ROOT}/.env"
PYTHON_BIN="${REPO_ROOT}/.venv/bin/python"

if [[ ! -f "${ENV_FILE}" ]]; then
  echo "Missing env file: ${ENV_FILE}" >&2
  exit 1
fi

if [[ ! -x "${PYTHON_BIN}" ]]; then
  echo "Missing Python runtime: ${PYTHON_BIN}" >&2
  exit 1
fi

CODEX_TELEGRAM_REPO_ROOT="${REPO_ROOT}" "${PYTHON_BIN}" - <<'PY'
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def load_env(env_path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def tracked_topics(state_dir: Path) -> list[tuple[int, int]]:
    topics: set[tuple[int, int]] = set()
    for database_path in sorted(state_dir.glob("gateway.db*")):
        if not database_path.is_file():
            continue
        connection = sqlite3.connect(str(database_path))
        try:
            table = connection.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table' AND name = 'bindings'
                """
            ).fetchone()
            if table is None:
                continue
            for chat_id, message_thread_id in connection.execute(
                """
                SELECT DISTINCT chat_id, message_thread_id
                FROM bindings
                ORDER BY chat_id, message_thread_id
                """
            ):
                topics.add((int(chat_id), int(message_thread_id)))
        finally:
            connection.close()
    return sorted(topics)


def call_telegram(base_url: str, method: str, payload: dict[str, int]) -> dict[str, object]:
    request = urllib.request.Request(
        f"{base_url}/{method}",
        data=urllib.parse.urlencode(payload).encode(),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "http_error": exc.read().decode(),
        }


def clear_current_state(database_path: Path) -> dict[str, int]:
    connection = sqlite3.connect(str(database_path))
    try:
        existing_tables = {
            row[0]
            for row in connection.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                """
            )
        }
        for table_name in ("bindings", "inbound_queue", "seen_events", "telegram_cursor"):
            if table_name in existing_tables:
                connection.execute(f"DELETE FROM {table_name}")
        connection.commit()
        counts: dict[str, int] = {}
        for table_name in ("bindings", "inbound_queue", "seen_events", "telegram_cursor"):
            if table_name in existing_tables:
                counts[table_name] = int(
                    connection.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]
                )
        return counts
    finally:
        connection.close()


repo_root = Path(os.environ["CODEX_TELEGRAM_REPO_ROOT"])
env = load_env(repo_root / ".env")
state_dir = repo_root / ".codex-telegram"
topic_rows = tracked_topics(state_dir)
if not topic_rows:
    print(json.dumps({"topics": [], "state_counts": {}}, indent=2))
    raise SystemExit(0)

base_url = f"https://api.telegram.org/bot{env['TELEGRAM_BOT_TOKEN']}"
results: list[dict[str, object]] = []
for chat_id, topic_id in topic_rows:
    payload = {"chat_id": chat_id, "message_thread_id": topic_id}
    delete_result = call_telegram(base_url, "deleteForumTopic", payload)
    if delete_result.get("ok") is True:
        results.append(
            {
                "chat_id": chat_id,
                "topic_id": topic_id,
                "status": "deleted",
                "response": delete_result,
            }
        )
        continue
    close_result = call_telegram(base_url, "closeForumTopic", payload)
    status = "closed" if close_result.get("ok") is True else "failed"
    results.append(
        {
            "chat_id": chat_id,
            "topic_id": topic_id,
            "status": status,
            "delete_response": delete_result,
            "close_response": close_result,
        }
    )

state_counts = clear_current_state(state_dir / "gateway.db")
print(
    json.dumps(
        {
            "topics": results,
            "state_counts": state_counts,
        },
        indent=2,
        ensure_ascii=False,
    )
)
PY
