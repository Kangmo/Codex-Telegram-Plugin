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
        rows = connection.execute(
            """
            SELECT id, cwd, updated_at
            FROM threads
            WHERE archived = 0
            """
        ).fetchall()
    finally:
        connection.close()

    ranked_rows = [
        row
        for row in rows
        if row["cwd"] in root_order
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
        rows = connection.execute(
            """
            SELECT id, cwd, title, updated_at
            FROM threads
            WHERE cwd = ?
              AND archived = 0
              AND (? IS NULL OR id != ?)
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (project_id, exclude_thread_id, exclude_thread_id, limit),
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
    ]
