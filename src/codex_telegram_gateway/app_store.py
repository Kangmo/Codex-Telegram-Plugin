import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppStoreThread:
    thread_id: str
    cwd: str
    title: str
    updated_at: int


def ensure_sidebar_workspace_root(codex_home: Path, workspace_root: str) -> bool:
    """Persist one workspace root into the Codex App sidebar state."""
    state_path = codex_home / ".codex-global-state.json"
    if state_path.exists():
        state = json.loads(state_path.read_text())
    else:
        state = {}

    changed = False
    for key in ("project-order", "electron-saved-workspace-roots"):
        values = state.get(key)
        if not isinstance(values, list):
            values = []
        normalized_values = [value for value in values if isinstance(value, str)]
        if workspace_root not in normalized_values:
            normalized_values.append(workspace_root)
            changed = True
        state[key] = normalized_values

    if changed or not state_path.exists():
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(json.dumps(state, indent=2, sort_keys=True))
    return changed


def sidebar_workspace_roots(codex_home: Path) -> list[str]:
    """Return project roots in the same order used by the Codex App sidebar."""
    state_path = codex_home / ".codex-global-state.json"
    if not state_path.exists():
        return []

    state = json.loads(state_path.read_text())
    ordered_roots: list[str] = []
    for key in ("project-order", "active-workspace-roots", "electron-saved-workspace-roots"):
        for root in state.get(key, []):
            if isinstance(root, str) and root not in ordered_roots:
                ordered_roots.append(root)
    return ordered_roots


def sidebar_thread_ids(codex_home: Path) -> list[str]:
    """Return non-archived thread ids grouped by sidebar project order."""
    roots = sidebar_workspace_roots(codex_home)
    if not roots:
        return []

    root_order = {root: index for index, root in enumerate(roots)}
    database_path = codex_home / "state_5.sqlite"
    if not database_path.exists():
        return []

    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    try:
        available_columns = _thread_table_columns(connection)
        select_columns = ["id", "cwd", "updated_at"]
        if "rollout_path" in available_columns:
            select_columns.append("rollout_path")
        if "first_user_message" in available_columns:
            select_columns.append("first_user_message")
        rows = connection.execute(
            f"""
            SELECT {", ".join(select_columns)}
            FROM threads
            WHERE archived = 0
            """
        ).fetchall()
    finally:
        connection.close()

    ranked_rows = [
        row
        for row in rows
        if row["cwd"] in root_order and _is_displayable_thread_row(row)
    ]
    ranked_rows.sort(
        key=lambda row: (
            root_order[str(row["cwd"])],
            -int(row["updated_at"]),
            str(row["id"]),
        )
    )
    return [str(row["id"]) for row in ranked_rows]


def thread_rollout_path(codex_home: Path, thread_id: str) -> Path | None:
    """Return the on-disk rollout log path for one Codex App thread."""
    database_path = codex_home / "state_5.sqlite"
    if not database_path.exists():
        return None

    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    try:
        row = connection.execute(
            """
            SELECT rollout_path
            FROM threads
            WHERE id = ?
            """,
            (thread_id,),
        ).fetchone()
    finally:
        connection.close()

    if row is None or not row["rollout_path"]:
        return None
    return Path(str(row["rollout_path"]))


def list_project_threads(
    codex_home: Path,
    project_id: str,
    *,
    exclude_thread_id: str | None = None,
    limit: int = 12,
) -> list[AppStoreThread]:
    """Return recent non-archived threads for one Codex App project root."""

    database_path = codex_home / "state_5.sqlite"
    if not database_path.exists():
        return []

    connection = sqlite3.connect(str(database_path))
    connection.row_factory = sqlite3.Row
    try:
        available_columns = _thread_table_columns(connection)
        select_columns = ["id", "cwd", "title", "updated_at"]
        if "rollout_path" in available_columns:
            select_columns.append("rollout_path")
        if "first_user_message" in available_columns:
            select_columns.append("first_user_message")
        rows = connection.execute(
            f"""
            SELECT {", ".join(select_columns)}
            FROM threads
            WHERE cwd = ?
              AND archived = 0
              AND (? IS NULL OR id != ?)
            ORDER BY updated_at DESC, id DESC
            """,
            (project_id, exclude_thread_id, exclude_thread_id),
        ).fetchall()
    finally:
        connection.close()

    return [
        AppStoreThread(
            thread_id=str(row["id"]),
            cwd=str(row["cwd"]),
            title=str(row["title"]),
            updated_at=int(row["updated_at"]),
        )
        for row in rows
        if _is_displayable_thread_row(row)
    ][:limit]


def _thread_table_columns(connection: sqlite3.Connection) -> set[str]:
    rows = connection.execute("PRAGMA table_info(threads)").fetchall()
    return {str(row["name"]) for row in rows}


def _is_displayable_thread_row(row: sqlite3.Row) -> bool:
    if "first_user_message" not in row.keys() and "rollout_path" not in row.keys():
        return True

    first_user_message = str(row["first_user_message"] or "").strip() if "first_user_message" in row.keys() else ""
    if first_user_message:
        return True

    rollout_path_value = str(row["rollout_path"] or "").strip() if "rollout_path" in row.keys() else ""
    if not rollout_path_value:
        return True
    return _rollout_has_material_activity(Path(rollout_path_value))


def _rollout_has_material_activity(rollout_path: Path) -> bool:
    if not rollout_path.exists():
        return False
    try:
        for raw_line in rollout_path.read_text().splitlines():
            line = raw_line.strip()
            if not line:
                continue
            record = json.loads(line)
            record_type = str(record.get("type") or "")
            if record_type == "session_meta":
                continue
            if record_type != "event_msg":
                return True
            payload = record.get("payload")
            if not isinstance(payload, dict):
                return True
            if str(payload.get("type") or "") != "thread_name_updated":
                return True
    except (json.JSONDecodeError, OSError):
        return True
    return False
