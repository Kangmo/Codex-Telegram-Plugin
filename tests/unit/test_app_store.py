import json
import sqlite3
from pathlib import Path

from codex_telegram_gateway.app_store import (
    AppStoreThread,
    ensure_sidebar_workspace_root,
    list_project_threads,
    sidebar_thread_ids,
    sidebar_workspace_roots,
)


def test_sidebar_workspace_roots_follow_app_state_order(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps(
            {
                "project-order": ["/proj-b"],
                "active-workspace-roots": ["/proj-a"],
                "electron-saved-workspace-roots": ["/proj-b", "/proj-c", "/proj-a"],
            }
        )
    )

    assert sidebar_workspace_roots(codex_home) == ["/proj-b", "/proj-a", "/proj-c"]


def test_sidebar_thread_ids_group_by_project_and_recent_first(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps(
            {
                "electron-saved-workspace-roots": ["/proj-b", "/proj-a"],
            }
        )
    )
    database_path = codex_home / "state_5.sqlite"
    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                cwd TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO threads (id, cwd, updated_at, archived)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("thread-b-older", "/proj-b", 10, 0),
                ("thread-b-newer", "/proj-b", 20, 0),
                ("thread-a-only", "/proj-a", 30, 0),
                ("thread-outside", "/proj-outside", 999, 0),
                ("thread-archived", "/proj-a", 1000, 1),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    assert sidebar_thread_ids(codex_home) == [
        "thread-b-newer",
        "thread-b-older",
        "thread-a-only",
    ]


def test_ensure_sidebar_workspace_root_appends_missing_root(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps(
            {
                "project-order": ["/proj-a"],
                "electron-saved-workspace-roots": ["/proj-b"],
            }
        )
    )

    changed = ensure_sidebar_workspace_root(codex_home, "/proj-c")
    state = json.loads((codex_home / ".codex-global-state.json").read_text())

    assert changed is True
    assert state["project-order"] == ["/proj-a", "/proj-c"]
    assert state["electron-saved-workspace-roots"] == ["/proj-b", "/proj-c"]


def test_ensure_sidebar_workspace_root_is_idempotent(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    (codex_home / ".codex-global-state.json").write_text(
        json.dumps(
            {
                "project-order": ["/proj-a"],
                "electron-saved-workspace-roots": ["/proj-a"],
            }
        )
    )

    changed = ensure_sidebar_workspace_root(codex_home, "/proj-a")

    assert changed is False


def test_list_project_threads_returns_recent_non_archived_threads_for_one_project(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    database_path = codex_home / "state_5.sqlite"
    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO threads (id, cwd, title, updated_at, archived)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("thread-new", "/proj-a", "New thread", 30, 0),
                ("thread-old", "/proj-a", "Old thread", 10, 0),
                ("thread-other", "/proj-b", "Other project", 40, 0),
                ("thread-archived", "/proj-a", "Archived", 50, 1),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    assert list_project_threads(codex_home, "/proj-a") == [
        AppStoreThread(
            thread_id="thread-new",
            cwd="/proj-a",
            title="New thread",
            updated_at=30,
        ),
        AppStoreThread(
            thread_id="thread-old",
            cwd="/proj-a",
            title="Old thread",
            updated_at=10,
        ),
    ]


def test_list_project_threads_applies_exclusion_and_limit(tmp_path: Path) -> None:
    codex_home = tmp_path / ".codex"
    codex_home.mkdir()
    database_path = codex_home / "state_5.sqlite"
    connection = sqlite3.connect(str(database_path))
    try:
        connection.execute(
            """
            CREATE TABLE threads (
                id TEXT PRIMARY KEY,
                cwd TEXT NOT NULL,
                title TEXT NOT NULL,
                updated_at INTEGER NOT NULL,
                archived INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO threads (id, cwd, title, updated_at, archived)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                ("thread-3", "/proj-a", "Third", 30, 0),
                ("thread-2", "/proj-a", "Second", 20, 0),
                ("thread-1", "/proj-a", "First", 10, 0),
            ],
        )
        connection.commit()
    finally:
        connection.close()

    assert [thread.thread_id for thread in list_project_threads(
        codex_home,
        "/proj-a",
        exclude_thread_id="thread-3",
        limit=1,
    )] == ["thread-2"]
