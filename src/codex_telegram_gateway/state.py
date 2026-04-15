import json
import sqlite3
from pathlib import Path
import time

from codex_telegram_gateway.models import (
    ACTIVE_BINDING_STATUS,
    Binding,
    CodexProject,
    HistoryViewState,
    InboundMessage,
    OutboundMessage,
    PendingTurn,
    RestoreViewState,
    ResumeViewState,
    TopicCreationJob,
    TopicLifecycle,
    TopicHistoryEntry,
    TopicProject,
)


class SqliteGatewayState:
    """SQLite-backed persistence boundary for thread-id to topic-id bindings."""

    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(str(self._database_path))
        self._connection.row_factory = sqlite3.Row
        self._initialize()

    def _initialize(self) -> None:
        """Create the small schema needed by the current test slice."""
        self._connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS bindings (
                codex_thread_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                topic_name TEXT,
                sync_mode TEXT NOT NULL,
                project_id TEXT,
                binding_status TEXT NOT NULL DEFAULT 'active',
                UNIQUE(chat_id, message_thread_id)
            );

            CREATE TABLE IF NOT EXISTS seen_events (
                codex_thread_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                PRIMARY KEY (codex_thread_id, event_id)
            );

            CREATE TABLE IF NOT EXISTS mirror_bindings (
                codex_thread_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                topic_name TEXT,
                sync_mode TEXT NOT NULL,
                project_id TEXT,
                binding_status TEXT NOT NULL DEFAULT 'active',
                PRIMARY KEY (codex_thread_id, chat_id),
                UNIQUE(chat_id, message_thread_id)
            );

            CREATE TABLE IF NOT EXISTS mirror_seen_events (
                codex_thread_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                PRIMARY KEY (codex_thread_id, chat_id, message_thread_id, event_id)
            );

            CREATE TABLE IF NOT EXISTS outbound_messages (
                codex_thread_id TEXT NOT NULL,
                event_id TEXT NOT NULL,
                telegram_message_ids_json TEXT NOT NULL,
                text TEXT NOT NULL,
                reply_markup_json TEXT,
                PRIMARY KEY (codex_thread_id, event_id)
            );

            CREATE TABLE IF NOT EXISTS mirror_outbound_messages (
                codex_thread_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                event_id TEXT NOT NULL,
                telegram_message_ids_json TEXT NOT NULL,
                text TEXT NOT NULL,
                reply_markup_json TEXT,
                PRIMARY KEY (codex_thread_id, chat_id, message_thread_id, event_id)
            );

            CREATE TABLE IF NOT EXISTS inbound_queue (
                telegram_update_id INTEGER PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                from_user_id INTEGER NOT NULL,
                codex_thread_id TEXT NOT NULL,
                text TEXT NOT NULL,
                local_image_paths_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS telegram_cursor (
                singleton_key INTEGER PRIMARY KEY CHECK (singleton_key = 1),
                next_update_id INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS projects (
                project_id TEXT PRIMARY KEY,
                project_name TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS topic_projects (
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                topic_name TEXT,
                project_id TEXT,
                picker_message_id INTEGER,
                pending_update_id INTEGER,
                pending_user_id INTEGER,
                pending_text TEXT,
                pending_local_image_paths_json TEXT NOT NULL DEFAULT '[]',
                browse_path TEXT,
                browse_page INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, message_thread_id)
            );

            CREATE TABLE IF NOT EXISTS pending_turns (
                codex_thread_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                turn_id TEXT NOT NULL,
                waiting_for_approval INTEGER NOT NULL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS topic_history (
                history_id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                local_image_paths_json TEXT NOT NULL DEFAULT '[]'
            );

            CREATE TABLE IF NOT EXISTS history_views (
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                codex_thread_id TEXT NOT NULL,
                page_index INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, message_thread_id)
            );

            CREATE TABLE IF NOT EXISTS resume_views (
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                project_id TEXT NOT NULL,
                page_index INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (chat_id, message_thread_id)
            );

            CREATE TABLE IF NOT EXISTS restore_views (
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL,
                codex_thread_id TEXT NOT NULL,
                issue_kind TEXT NOT NULL,
                PRIMARY KEY (chat_id, message_thread_id)
            );

            CREATE TABLE IF NOT EXISTS passthrough_commands (
                command_name TEXT PRIMARY KEY,
                seen_at REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS command_menu_state (
                scope_key TEXT PRIMARY KEY,
                menu_hash TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS topic_lifecycles (
                codex_thread_id TEXT PRIMARY KEY,
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                bound_at REAL,
                last_inbound_at REAL,
                last_outbound_at REAL,
                completed_at REAL
            );

            CREATE TABLE IF NOT EXISTS topic_project_activity (
                chat_id INTEGER NOT NULL,
                message_thread_id INTEGER NOT NULL,
                last_seen_at REAL NOT NULL,
                PRIMARY KEY (chat_id, message_thread_id)
            );

            CREATE TABLE IF NOT EXISTS topic_creation_queue (
                codex_thread_id TEXT NOT NULL,
                chat_id INTEGER NOT NULL,
                topic_name TEXT NOT NULL,
                project_id TEXT,
                retry_after_at REAL,
                PRIMARY KEY (codex_thread_id, chat_id)
            );
            """
        )
        self._ensure_bindings_column("project_id", "TEXT")
        self._ensure_bindings_column("binding_status", "TEXT NOT NULL DEFAULT 'active'")
        self._ensure_table_column("inbound_queue", "local_image_paths_json", "TEXT NOT NULL DEFAULT '[]'")
        self._ensure_table_column("outbound_messages", "reply_markup_json", "TEXT")
        self._ensure_table_column("topic_projects", "pending_update_id", "INTEGER")
        self._ensure_table_column("topic_projects", "pending_user_id", "INTEGER")
        self._ensure_table_column("topic_projects", "pending_text", "TEXT")
        self._ensure_table_column(
            "topic_projects",
            "pending_local_image_paths_json",
            "TEXT NOT NULL DEFAULT '[]'",
        )
        self._ensure_table_column("topic_projects", "browse_path", "TEXT")
        self._ensure_table_column("topic_projects", "browse_page", "INTEGER NOT NULL DEFAULT 0")
        self._connection.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_bindings_topic_identity
            ON bindings (chat_id, message_thread_id)
            """
        )
        self._connection.commit()

    def create_binding(self, binding: Binding) -> Binding:
        # Persist the stable thread-id to topic-id mapping; topic_name is metadata only.
        self._connection.execute(
            """
            INSERT OR REPLACE INTO bindings (
                codex_thread_id,
                chat_id,
                message_thread_id,
                topic_name,
                sync_mode,
                project_id,
                binding_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                binding.codex_thread_id,
                binding.chat_id,
                binding.message_thread_id,
                binding.topic_name,
                binding.sync_mode,
                binding.project_id,
                binding.binding_status,
            ),
        )
        self._connection.commit()
        return binding

    def list_bindings(self) -> list[Binding]:
        rows = self._connection.execute(
            """
            SELECT codex_thread_id, chat_id, message_thread_id, topic_name, sync_mode, project_id, binding_status
            FROM bindings
            ORDER BY codex_thread_id
            """
        ).fetchall()
        return [self._binding_from_row(row) for row in rows]

    def get_binding_by_thread(self, codex_thread_id: str) -> Binding:
        row = self._connection.execute(
            """
            SELECT codex_thread_id, chat_id, message_thread_id, topic_name, sync_mode, project_id, binding_status
            FROM bindings
            WHERE codex_thread_id = ?
            """,
            (codex_thread_id,),
        ).fetchone()
        if row is None:
            raise KeyError(codex_thread_id)
        return self._binding_from_row(row)

    def get_binding_by_topic(self, chat_id: int, message_thread_id: int) -> Binding | None:
        row = self._connection.execute(
            """
            SELECT codex_thread_id, chat_id, message_thread_id, topic_name, sync_mode, project_id, binding_status
            FROM bindings
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        ).fetchone()
        if row is None:
            return None
        return self._binding_from_row(row)

    def delete_binding(self, codex_thread_id: str) -> None:
        self._connection.execute(
            """
            DELETE FROM bindings
            WHERE codex_thread_id = ?
            """,
            (codex_thread_id,),
        )
        self._connection.commit()

    def upsert_mirror_binding(self, binding: Binding) -> Binding:
        self._connection.execute(
            """
            INSERT INTO mirror_bindings (
                codex_thread_id,
                chat_id,
                message_thread_id,
                topic_name,
                sync_mode,
                project_id,
                binding_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(codex_thread_id, chat_id)
            DO UPDATE SET
                message_thread_id = excluded.message_thread_id,
                topic_name = excluded.topic_name,
                sync_mode = excluded.sync_mode,
                project_id = excluded.project_id,
                binding_status = excluded.binding_status
            """,
            (
                binding.codex_thread_id,
                binding.chat_id,
                binding.message_thread_id,
                binding.topic_name,
                binding.sync_mode,
                binding.project_id,
                binding.binding_status,
            ),
        )
        self._connection.commit()
        return binding

    def list_mirror_bindings(self) -> list[Binding]:
        rows = self._connection.execute(
            """
            SELECT codex_thread_id, chat_id, message_thread_id, topic_name, sync_mode, project_id, binding_status
            FROM mirror_bindings
            ORDER BY codex_thread_id, chat_id
            """
        ).fetchall()
        return [self._binding_from_row(row) for row in rows]

    def list_mirror_bindings_for_thread(self, codex_thread_id: str) -> list[Binding]:
        rows = self._connection.execute(
            """
            SELECT codex_thread_id, chat_id, message_thread_id, topic_name, sync_mode, project_id, binding_status
            FROM mirror_bindings
            WHERE codex_thread_id = ?
            ORDER BY chat_id
            """,
            (codex_thread_id,),
        ).fetchall()
        return [self._binding_from_row(row) for row in rows]

    def get_mirror_binding_by_topic(self, chat_id: int, message_thread_id: int) -> Binding | None:
        row = self._connection.execute(
            """
            SELECT codex_thread_id, chat_id, message_thread_id, topic_name, sync_mode, project_id, binding_status
            FROM mirror_bindings
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        ).fetchone()
        if row is None:
            return None
        return self._binding_from_row(row)

    def delete_mirror_binding(self, codex_thread_id: str, *, chat_id: int) -> None:
        self._connection.execute(
            """
            DELETE FROM mirror_bindings
            WHERE codex_thread_id = ? AND chat_id = ?
            """,
            (codex_thread_id, chat_id),
        )
        self._connection.commit()

    def upsert_project(self, project: CodexProject) -> CodexProject:
        self._connection.execute(
            """
            INSERT INTO projects (project_id, project_name)
            VALUES (?, ?)
            ON CONFLICT(project_id)
            DO UPDATE SET project_name = excluded.project_name
            """,
            (project.project_id, project.project_name),
        )
        self._connection.commit()
        return project

    def list_projects(self) -> list[CodexProject]:
        rows = self._connection.execute(
            """
            SELECT project_id, project_name
            FROM projects
            ORDER BY project_name, project_id
            """
        ).fetchall()
        return [
            CodexProject(project_id=row["project_id"], project_name=row["project_name"])
            for row in rows
        ]

    def get_project(self, project_id: str) -> CodexProject:
        row = self._connection.execute(
            """
            SELECT project_id, project_name
            FROM projects
            WHERE project_id = ?
            """,
            (project_id,),
        ).fetchone()
        if row is None:
            raise KeyError(project_id)
        return CodexProject(project_id=row["project_id"], project_name=row["project_name"])

    def upsert_topic_project(self, topic_project: TopicProject) -> TopicProject:
        self._connection.execute(
            """
            INSERT INTO topic_projects (
                chat_id,
                message_thread_id,
                topic_name,
                project_id,
                picker_message_id,
                pending_update_id,
                pending_user_id,
                pending_text,
                pending_local_image_paths_json,
                browse_path,
                browse_page
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_thread_id)
            DO UPDATE SET
                topic_name = excluded.topic_name,
                project_id = excluded.project_id,
                picker_message_id = excluded.picker_message_id,
                pending_update_id = excluded.pending_update_id,
                pending_user_id = excluded.pending_user_id,
                pending_text = excluded.pending_text,
                pending_local_image_paths_json = excluded.pending_local_image_paths_json,
                browse_path = excluded.browse_path,
                browse_page = excluded.browse_page
            """,
            (
                topic_project.chat_id,
                topic_project.message_thread_id,
                topic_project.topic_name,
                topic_project.project_id,
                topic_project.picker_message_id,
                topic_project.pending_update_id,
                topic_project.pending_user_id,
                topic_project.pending_text,
                _paths_to_json(topic_project.pending_local_image_paths),
                topic_project.browse_path,
                topic_project.browse_page,
            ),
        )
        self._connection.commit()
        return topic_project

    def get_topic_project(self, chat_id: int, message_thread_id: int) -> TopicProject | None:
        row = self._connection.execute(
            """
            SELECT
                chat_id,
                message_thread_id,
                topic_name,
                project_id,
                picker_message_id,
                pending_update_id,
                pending_user_id,
                pending_text,
                pending_local_image_paths_json,
                browse_path,
                browse_page
            FROM topic_projects
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        ).fetchone()
        if row is None:
            return None
        return TopicProject(
            chat_id=row["chat_id"],
            message_thread_id=row["message_thread_id"],
            topic_name=row["topic_name"],
            project_id=row["project_id"],
            picker_message_id=row["picker_message_id"],
            pending_update_id=row["pending_update_id"],
            pending_user_id=row["pending_user_id"],
            pending_text=row["pending_text"],
            pending_local_image_paths=_paths_from_json(row["pending_local_image_paths_json"]),
            browse_path=row["browse_path"],
            browse_page=row["browse_page"] or 0,
        )

    def delete_topic_project(self, chat_id: int, message_thread_id: int) -> None:
        self._connection.execute(
            """
            DELETE FROM topic_projects
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        )
        self._connection.commit()

    def mark_event_seen(self, codex_thread_id: str, event_id: str) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO seen_events (codex_thread_id, event_id)
            VALUES (?, ?)
            """,
            (codex_thread_id, event_id),
        )
        self._connection.commit()

    def has_seen_event(self, codex_thread_id: str, event_id: str) -> bool:
        row = self._connection.execute(
            """
            SELECT 1
            FROM seen_events
            WHERE codex_thread_id = ? AND event_id = ?
            """,
            (codex_thread_id, event_id),
        ).fetchone()
        return row is not None

    def delete_seen_event(self, codex_thread_id: str, event_id: str) -> None:
        self._connection.execute(
            """
            DELETE FROM seen_events
            WHERE codex_thread_id = ? AND event_id = ?
            """,
            (codex_thread_id, event_id),
        )
        self._connection.commit()

    def mark_mirror_event_seen(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO mirror_seen_events (
                codex_thread_id,
                chat_id,
                message_thread_id,
                event_id
            ) VALUES (?, ?, ?, ?)
            """,
            (codex_thread_id, chat_id, message_thread_id, event_id),
        )
        self._connection.commit()

    def has_mirror_seen_event(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> bool:
        row = self._connection.execute(
            """
            SELECT 1
            FROM mirror_seen_events
            WHERE codex_thread_id = ? AND chat_id = ? AND message_thread_id = ? AND event_id = ?
            """,
            (codex_thread_id, chat_id, message_thread_id, event_id),
        ).fetchone()
        return row is not None

    def delete_mirror_seen_event(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> None:
        self._connection.execute(
            """
            DELETE FROM mirror_seen_events
            WHERE codex_thread_id = ? AND chat_id = ? AND message_thread_id = ? AND event_id = ?
            """,
            (codex_thread_id, chat_id, message_thread_id, event_id),
        )
        self._connection.commit()

    def enqueue_inbound(self, inbound_message: InboundMessage) -> None:
        self._connection.execute(
            """
            INSERT OR IGNORE INTO inbound_queue (
                telegram_update_id,
                chat_id,
                message_thread_id,
                from_user_id,
                codex_thread_id,
                text,
                local_image_paths_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                inbound_message.telegram_update_id,
                inbound_message.chat_id,
                inbound_message.message_thread_id,
                inbound_message.from_user_id,
                inbound_message.codex_thread_id,
                inbound_message.text,
                _paths_to_json(inbound_message.local_image_paths),
            ),
        )
        self._connection.commit()

    def list_pending_inbound(self) -> list[InboundMessage]:
        rows = self._connection.execute(
            """
            SELECT
                telegram_update_id,
                chat_id,
                message_thread_id,
                from_user_id,
                codex_thread_id,
                text,
                local_image_paths_json
            FROM inbound_queue
            ORDER BY telegram_update_id
            """
        ).fetchall()
        return [
            InboundMessage(
                telegram_update_id=row["telegram_update_id"],
                chat_id=row["chat_id"],
                message_thread_id=row["message_thread_id"],
                from_user_id=row["from_user_id"],
                codex_thread_id=row["codex_thread_id"],
                text=row["text"],
                local_image_paths=_paths_from_json(row["local_image_paths_json"]),
            )
            for row in rows
        ]

    def mark_inbound_delivered(self, telegram_update_id: int) -> None:
        self._connection.execute(
            "DELETE FROM inbound_queue WHERE telegram_update_id = ?",
            (telegram_update_id,),
        )
        self._connection.commit()

    def delete_pending_inbound_for_thread(self, codex_thread_id: str) -> None:
        self._connection.execute(
            """
            DELETE FROM inbound_queue
            WHERE codex_thread_id = ?
            """,
            (codex_thread_id,),
        )
        self._connection.commit()

    def set_telegram_cursor(self, update_id: int) -> None:
        self._connection.execute(
            """
            INSERT INTO telegram_cursor (singleton_key, next_update_id)
            VALUES (1, ?)
            ON CONFLICT(singleton_key)
            DO UPDATE SET next_update_id = excluded.next_update_id
            """,
            (update_id,),
        )
        self._connection.commit()

    def get_telegram_cursor(self) -> int:
        row = self._connection.execute(
            "SELECT next_update_id FROM telegram_cursor WHERE singleton_key = 1"
        ).fetchone()
        if row is None:
            return 0
        return int(row["next_update_id"])

    def pending_inbound_count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) AS total FROM inbound_queue").fetchone()
        return int(row["total"])

    def upsert_outbound_message(self, outbound_message: OutboundMessage) -> OutboundMessage:
        self._connection.execute(
            """
            INSERT INTO outbound_messages (
                codex_thread_id,
                event_id,
                telegram_message_ids_json,
                text,
                reply_markup_json
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(codex_thread_id, event_id)
            DO UPDATE SET
                telegram_message_ids_json = excluded.telegram_message_ids_json,
                text = excluded.text,
                reply_markup_json = excluded.reply_markup_json
            """,
            (
                outbound_message.codex_thread_id,
                outbound_message.event_id,
                json.dumps(list(outbound_message.telegram_message_ids)),
                outbound_message.text,
                _json_or_none(outbound_message.reply_markup),
            ),
        )
        self._connection.commit()
        return outbound_message

    def get_outbound_message(self, codex_thread_id: str, event_id: str) -> OutboundMessage | None:
        row = self._connection.execute(
            """
            SELECT
                codex_thread_id,
                event_id,
                telegram_message_ids_json,
                text,
                reply_markup_json
            FROM outbound_messages
            WHERE codex_thread_id = ? AND event_id = ?
            """,
            (codex_thread_id, event_id),
        ).fetchone()
        if row is None:
            return None
        return OutboundMessage(
            codex_thread_id=row["codex_thread_id"],
            event_id=row["event_id"],
            telegram_message_ids=_message_ids_from_json(row["telegram_message_ids_json"]),
            text=row["text"],
            reply_markup=_reply_markup_from_json(row["reply_markup_json"]),
        )

    def delete_outbound_messages(self, codex_thread_id: str) -> None:
        self._connection.execute(
            """
            DELETE FROM outbound_messages
            WHERE codex_thread_id = ?
            """,
            (codex_thread_id,),
        )
        self._connection.commit()

    def upsert_mirror_outbound_message(
        self,
        outbound_message: OutboundMessage,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> OutboundMessage:
        self._connection.execute(
            """
            INSERT INTO mirror_outbound_messages (
                codex_thread_id,
                chat_id,
                message_thread_id,
                event_id,
                telegram_message_ids_json,
                text,
                reply_markup_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(codex_thread_id, chat_id, message_thread_id, event_id)
            DO UPDATE SET
                telegram_message_ids_json = excluded.telegram_message_ids_json,
                text = excluded.text,
                reply_markup_json = excluded.reply_markup_json
            """,
            (
                outbound_message.codex_thread_id,
                chat_id,
                message_thread_id,
                outbound_message.event_id,
                json.dumps(list(outbound_message.telegram_message_ids)),
                outbound_message.text,
                _json_or_none(outbound_message.reply_markup),
            ),
        )
        self._connection.commit()
        return outbound_message

    def get_mirror_outbound_message(
        self,
        codex_thread_id: str,
        event_id: str,
        *,
        chat_id: int,
        message_thread_id: int,
    ) -> OutboundMessage | None:
        row = self._connection.execute(
            """
            SELECT
                codex_thread_id,
                event_id,
                telegram_message_ids_json,
                text,
                reply_markup_json
            FROM mirror_outbound_messages
            WHERE codex_thread_id = ? AND chat_id = ? AND message_thread_id = ? AND event_id = ?
            """,
            (codex_thread_id, chat_id, message_thread_id, event_id),
        ).fetchone()
        if row is None:
            return None
        return OutboundMessage(
            codex_thread_id=row["codex_thread_id"],
            event_id=row["event_id"],
            telegram_message_ids=_message_ids_from_json(row["telegram_message_ids_json"]),
            text=row["text"],
            reply_markup=_reply_markup_from_json(row["reply_markup_json"]),
        )

    def delete_mirror_outbound_messages(self, codex_thread_id: str, *, chat_id: int) -> None:
        self._connection.execute(
            """
            DELETE FROM mirror_outbound_messages
            WHERE codex_thread_id = ? AND chat_id = ?
            """,
            (codex_thread_id, chat_id),
        )
        self._connection.commit()

    def record_topic_history(
        self,
        chat_id: int,
        message_thread_id: int,
        *,
        text: str = "",
        local_image_paths: tuple[str, ...] = (),
    ) -> None:
        normalized_text = text.strip()
        if not normalized_text and not local_image_paths:
            return
        latest = self.list_topic_history(chat_id, message_thread_id, limit=1)
        candidate = TopicHistoryEntry(
            text=normalized_text,
            local_image_paths=local_image_paths,
        )
        if latest and latest[0] == candidate:
            return
        self._connection.execute(
            """
            INSERT INTO topic_history (
                chat_id,
                message_thread_id,
                text,
                local_image_paths_json
            ) VALUES (?, ?, ?, ?)
            """,
            (
                chat_id,
                message_thread_id,
                normalized_text,
                _paths_to_json(local_image_paths),
            ),
        )
        self._connection.execute(
            """
            DELETE FROM topic_history
            WHERE history_id NOT IN (
                SELECT history_id
                FROM topic_history
                WHERE chat_id = ? AND message_thread_id = ?
                ORDER BY history_id DESC
                LIMIT 20
            )
            AND chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id, chat_id, message_thread_id),
        )
        self._connection.commit()

    def list_topic_history(
        self,
        chat_id: int,
        message_thread_id: int,
        *,
        limit: int = 20,
    ) -> list[TopicHistoryEntry]:
        rows = self._connection.execute(
            """
            SELECT
                text,
                local_image_paths_json
            FROM topic_history
            WHERE chat_id = ? AND message_thread_id = ?
            ORDER BY history_id DESC
            LIMIT ?
            """,
            (chat_id, message_thread_id, limit),
        ).fetchall()
        return [
            TopicHistoryEntry(
                text=row["text"],
                local_image_paths=_paths_from_json(row["local_image_paths_json"]),
            )
            for row in rows
        ]

    def delete_topic_history(self, chat_id: int, message_thread_id: int) -> None:
        self._connection.execute(
            """
            DELETE FROM topic_history
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        )
        self._connection.commit()

    def remember_passthrough_command(self, command_name: str) -> bool:
        cursor = self._connection.execute(
            """
            INSERT INTO passthrough_commands (command_name, seen_at)
            VALUES (?, ?)
            ON CONFLICT(command_name) DO NOTHING
            """,
            (command_name, time.time()),
        )
        self._connection.commit()
        return cursor.rowcount > 0

    def list_passthrough_commands(self) -> tuple[str, ...]:
        rows = self._connection.execute(
            """
            SELECT command_name
            FROM passthrough_commands
            ORDER BY command_name ASC
            """
        ).fetchall()
        return tuple(str(row["command_name"]) for row in rows)

    def get_registered_command_menu_hash(self, scope_key: str) -> str | None:
        row = self._connection.execute(
            """
            SELECT menu_hash
            FROM command_menu_state
            WHERE scope_key = ?
            """,
            (scope_key,),
        ).fetchone()
        if row is None:
            return None
        return str(row["menu_hash"])

    def set_registered_command_menu_hash(self, scope_key: str, menu_hash: str) -> None:
        self._connection.execute(
            """
            INSERT INTO command_menu_state (scope_key, menu_hash)
            VALUES (?, ?)
            ON CONFLICT(scope_key) DO UPDATE SET
                menu_hash = excluded.menu_hash
            """,
            (scope_key, menu_hash),
        )
        self._connection.commit()

    def upsert_history_view(self, history_view: HistoryViewState) -> HistoryViewState:
        self._connection.execute(
            """
            INSERT INTO history_views (
                chat_id,
                message_thread_id,
                message_id,
                codex_thread_id,
                page_index
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_thread_id)
            DO UPDATE SET
                message_id = excluded.message_id,
                codex_thread_id = excluded.codex_thread_id,
                page_index = excluded.page_index
            """,
            (
                history_view.chat_id,
                history_view.message_thread_id,
                history_view.message_id,
                history_view.codex_thread_id,
                history_view.page_index,
            ),
        )
        self._connection.commit()
        return history_view

    def get_history_view(self, chat_id: int, message_thread_id: int) -> HistoryViewState | None:
        row = self._connection.execute(
            """
            SELECT
                chat_id,
                message_thread_id,
                message_id,
                codex_thread_id,
                page_index
            FROM history_views
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        ).fetchone()
        if row is None:
            return None
        return HistoryViewState(
            chat_id=row["chat_id"],
            message_thread_id=row["message_thread_id"],
            message_id=row["message_id"],
            codex_thread_id=row["codex_thread_id"],
            page_index=row["page_index"],
        )

    def delete_history_view(self, chat_id: int, message_thread_id: int) -> None:
        self._connection.execute(
            """
            DELETE FROM history_views
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        )
        self._connection.commit()

    def upsert_resume_view(self, resume_view: ResumeViewState) -> ResumeViewState:
        self._connection.execute(
            """
            INSERT INTO resume_views (
                chat_id,
                message_thread_id,
                message_id,
                project_id,
                page_index
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_thread_id)
            DO UPDATE SET
                message_id = excluded.message_id,
                project_id = excluded.project_id,
                page_index = excluded.page_index
            """,
            (
                resume_view.chat_id,
                resume_view.message_thread_id,
                resume_view.message_id,
                resume_view.project_id,
                resume_view.page_index,
            ),
        )
        self._connection.commit()
        return resume_view

    def get_resume_view(self, chat_id: int, message_thread_id: int) -> ResumeViewState | None:
        row = self._connection.execute(
            """
            SELECT
                chat_id,
                message_thread_id,
                message_id,
                project_id,
                page_index
            FROM resume_views
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        ).fetchone()
        if row is None:
            return None
        return ResumeViewState(
            chat_id=row["chat_id"],
            message_thread_id=row["message_thread_id"],
            message_id=row["message_id"],
            project_id=row["project_id"],
            page_index=row["page_index"],
        )

    def delete_resume_view(self, chat_id: int, message_thread_id: int) -> None:
        self._connection.execute(
            """
            DELETE FROM resume_views
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        )
        self._connection.commit()

    def upsert_restore_view(self, restore_view: RestoreViewState) -> RestoreViewState:
        self._connection.execute(
            """
            INSERT INTO restore_views (
                chat_id,
                message_thread_id,
                message_id,
                codex_thread_id,
                issue_kind
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(chat_id, message_thread_id)
            DO UPDATE SET
                message_id = excluded.message_id,
                codex_thread_id = excluded.codex_thread_id,
                issue_kind = excluded.issue_kind
            """,
            (
                restore_view.chat_id,
                restore_view.message_thread_id,
                restore_view.message_id,
                restore_view.codex_thread_id,
                restore_view.issue_kind,
            ),
        )
        self._connection.commit()
        return restore_view

    def get_restore_view(self, chat_id: int, message_thread_id: int) -> RestoreViewState | None:
        row = self._connection.execute(
            """
            SELECT
                chat_id,
                message_thread_id,
                message_id,
                codex_thread_id,
                issue_kind
            FROM restore_views
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        ).fetchone()
        if row is None:
            return None
        return RestoreViewState(
            chat_id=row["chat_id"],
            message_thread_id=row["message_thread_id"],
            message_id=row["message_id"],
            codex_thread_id=row["codex_thread_id"],
            issue_kind=row["issue_kind"],
        )

    def delete_restore_view(self, chat_id: int, message_thread_id: int) -> None:
        self._connection.execute(
            """
            DELETE FROM restore_views
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        )
        self._connection.commit()

    def upsert_pending_turn(self, pending_turn: PendingTurn) -> PendingTurn:
        self._connection.execute(
            """
            INSERT INTO pending_turns (
                codex_thread_id,
                chat_id,
                message_thread_id,
                turn_id,
                waiting_for_approval
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(codex_thread_id)
            DO UPDATE SET
                chat_id = excluded.chat_id,
                message_thread_id = excluded.message_thread_id,
                turn_id = excluded.turn_id,
                waiting_for_approval = excluded.waiting_for_approval
            """,
            (
                pending_turn.codex_thread_id,
                pending_turn.chat_id,
                pending_turn.message_thread_id,
                pending_turn.turn_id,
                1 if pending_turn.waiting_for_approval else 0,
            ),
        )
        self._connection.commit()
        return pending_turn

    def get_pending_turn(self, codex_thread_id: str) -> PendingTurn | None:
        row = self._connection.execute(
            """
            SELECT
                codex_thread_id,
                chat_id,
                message_thread_id,
                turn_id,
                waiting_for_approval
            FROM pending_turns
            WHERE codex_thread_id = ?
            """,
            (codex_thread_id,),
        ).fetchone()
        if row is None:
            return None
        return self._pending_turn_from_row(row)

    def list_pending_turns(self) -> list[PendingTurn]:
        rows = self._connection.execute(
            """
            SELECT
                codex_thread_id,
                chat_id,
                message_thread_id,
                turn_id,
                waiting_for_approval
            FROM pending_turns
            ORDER BY codex_thread_id
            """
        ).fetchall()
        return [self._pending_turn_from_row(row) for row in rows]

    def delete_pending_turn(self, codex_thread_id: str) -> None:
        self._connection.execute(
            "DELETE FROM pending_turns WHERE codex_thread_id = ?",
            (codex_thread_id,),
        )
        self._connection.commit()

    def upsert_topic_lifecycle(self, topic_lifecycle: TopicLifecycle) -> TopicLifecycle:
        self._connection.execute(
            """
            INSERT INTO topic_lifecycles (
                codex_thread_id,
                chat_id,
                message_thread_id,
                bound_at,
                last_inbound_at,
                last_outbound_at,
                completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(codex_thread_id)
            DO UPDATE SET
                chat_id = excluded.chat_id,
                message_thread_id = excluded.message_thread_id,
                bound_at = excluded.bound_at,
                last_inbound_at = excluded.last_inbound_at,
                last_outbound_at = excluded.last_outbound_at,
                completed_at = excluded.completed_at
            """,
            (
                topic_lifecycle.codex_thread_id,
                topic_lifecycle.chat_id,
                topic_lifecycle.message_thread_id,
                topic_lifecycle.bound_at,
                topic_lifecycle.last_inbound_at,
                topic_lifecycle.last_outbound_at,
                topic_lifecycle.completed_at,
            ),
        )
        self._connection.commit()
        return topic_lifecycle

    def get_topic_lifecycle(self, codex_thread_id: str) -> TopicLifecycle | None:
        row = self._connection.execute(
            """
            SELECT
                codex_thread_id,
                chat_id,
                message_thread_id,
                bound_at,
                last_inbound_at,
                last_outbound_at,
                completed_at
            FROM topic_lifecycles
            WHERE codex_thread_id = ?
            """,
            (codex_thread_id,),
        ).fetchone()
        if row is None:
            return None
        return self._topic_lifecycle_from_row(row)

    def list_topic_lifecycles(self) -> list[TopicLifecycle]:
        rows = self._connection.execute(
            """
            SELECT
                codex_thread_id,
                chat_id,
                message_thread_id,
                bound_at,
                last_inbound_at,
                last_outbound_at,
                completed_at
            FROM topic_lifecycles
            ORDER BY codex_thread_id
            """
        ).fetchall()
        return [self._topic_lifecycle_from_row(row) for row in rows]

    def delete_topic_lifecycle(self, codex_thread_id: str) -> None:
        self._connection.execute(
            "DELETE FROM topic_lifecycles WHERE codex_thread_id = ?",
            (codex_thread_id,),
        )
        self._connection.commit()

    def set_topic_project_last_seen(self, chat_id: int, message_thread_id: int, seen_at: float) -> None:
        self._connection.execute(
            """
            INSERT INTO topic_project_activity (
                chat_id,
                message_thread_id,
                last_seen_at
            ) VALUES (?, ?, ?)
            ON CONFLICT(chat_id, message_thread_id)
            DO UPDATE SET
                last_seen_at = excluded.last_seen_at
            """,
            (chat_id, message_thread_id, seen_at),
        )
        self._connection.commit()

    def get_topic_project_last_seen(self, chat_id: int, message_thread_id: int) -> float | None:
        row = self._connection.execute(
            """
            SELECT last_seen_at
            FROM topic_project_activity
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        ).fetchone()
        if row is None:
            return None
        return float(row["last_seen_at"])

    def list_topic_project_last_seen(self) -> list[tuple[int, int, float]]:
        rows = self._connection.execute(
            """
            SELECT chat_id, message_thread_id, last_seen_at
            FROM topic_project_activity
            ORDER BY chat_id, message_thread_id
            """
        ).fetchall()
        return [
            (int(row["chat_id"]), int(row["message_thread_id"]), float(row["last_seen_at"]))
            for row in rows
        ]

    def delete_topic_project_last_seen(self, chat_id: int, message_thread_id: int) -> None:
        self._connection.execute(
            """
            DELETE FROM topic_project_activity
            WHERE chat_id = ? AND message_thread_id = ?
            """,
            (chat_id, message_thread_id),
        )
        self._connection.commit()

    def prune_orphan_topic_history(self, live_topics: set[tuple[int, int]]) -> None:
        rows = self._connection.execute(
            """
            SELECT DISTINCT chat_id, message_thread_id
            FROM topic_history
            """
        ).fetchall()
        for row in rows:
            topic_key = (int(row["chat_id"]), int(row["message_thread_id"]))
            if topic_key in live_topics:
                continue
            self._connection.execute(
                """
                DELETE FROM topic_history
                WHERE chat_id = ? AND message_thread_id = ?
                """,
                topic_key,
            )
        self._connection.commit()

    def upsert_topic_creation_job(self, topic_creation_job: TopicCreationJob) -> TopicCreationJob:
        self._connection.execute(
            """
            INSERT INTO topic_creation_queue (
                codex_thread_id,
                chat_id,
                topic_name,
                project_id,
                retry_after_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(codex_thread_id, chat_id)
            DO UPDATE SET
                topic_name = excluded.topic_name,
                project_id = excluded.project_id,
                retry_after_at = excluded.retry_after_at
            """,
            (
                topic_creation_job.codex_thread_id,
                topic_creation_job.chat_id,
                topic_creation_job.topic_name,
                topic_creation_job.project_id,
                topic_creation_job.retry_after_at,
            ),
        )
        self._connection.commit()
        return topic_creation_job

    def get_topic_creation_job(self, codex_thread_id: str, chat_id: int) -> TopicCreationJob | None:
        row = self._connection.execute(
            """
            SELECT codex_thread_id, chat_id, topic_name, project_id, retry_after_at
            FROM topic_creation_queue
            WHERE codex_thread_id = ? AND chat_id = ?
            """,
            (codex_thread_id, chat_id),
        ).fetchone()
        if row is None:
            return None
        return TopicCreationJob(
            codex_thread_id=row["codex_thread_id"],
            chat_id=row["chat_id"],
            topic_name=row["topic_name"],
            project_id=row["project_id"],
            retry_after_at=row["retry_after_at"],
        )

    def list_topic_creation_jobs(self) -> list[TopicCreationJob]:
        rows = self._connection.execute(
            """
            SELECT codex_thread_id, chat_id, topic_name, project_id, retry_after_at
            FROM topic_creation_queue
            ORDER BY chat_id, codex_thread_id
            """
        ).fetchall()
        return [
            TopicCreationJob(
                codex_thread_id=row["codex_thread_id"],
                chat_id=row["chat_id"],
                topic_name=row["topic_name"],
                project_id=row["project_id"],
                retry_after_at=row["retry_after_at"],
            )
            for row in rows
        ]

    def delete_topic_creation_job(self, codex_thread_id: str, chat_id: int) -> None:
        self._connection.execute(
            """
            DELETE FROM topic_creation_queue
            WHERE codex_thread_id = ? AND chat_id = ?
            """,
            (codex_thread_id, chat_id),
        )
        self._connection.commit()

    @staticmethod
    def _binding_from_row(row: sqlite3.Row) -> Binding:
        return Binding(
            codex_thread_id=row["codex_thread_id"],
            chat_id=row["chat_id"],
            message_thread_id=row["message_thread_id"],
            topic_name=row["topic_name"],
            sync_mode=row["sync_mode"],
            project_id=row["project_id"],
            binding_status=row["binding_status"] or ACTIVE_BINDING_STATUS,
        )

    @staticmethod
    def _pending_turn_from_row(row: sqlite3.Row) -> PendingTurn:
        return PendingTurn(
            codex_thread_id=row["codex_thread_id"],
            chat_id=row["chat_id"],
            message_thread_id=row["message_thread_id"],
            turn_id=row["turn_id"],
            waiting_for_approval=bool(row["waiting_for_approval"]),
        )

    @staticmethod
    def _topic_lifecycle_from_row(row: sqlite3.Row) -> TopicLifecycle:
        return TopicLifecycle(
            codex_thread_id=row["codex_thread_id"],
            chat_id=row["chat_id"],
            message_thread_id=row["message_thread_id"],
            bound_at=row["bound_at"],
            last_inbound_at=row["last_inbound_at"],
            last_outbound_at=row["last_outbound_at"],
            completed_at=row["completed_at"],
        )

    def _ensure_bindings_column(self, column_name: str, column_type: str) -> None:
        self._ensure_table_column("bindings", column_name, column_type)

    def _ensure_table_column(self, table_name: str, column_name: str, column_type: str) -> None:
        existing_columns = {
            row["name"]
            for row in self._connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        if column_name in existing_columns:
            return
        self._connection.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def _paths_to_json(paths: tuple[str, ...]) -> str:
    return json.dumps(list(paths))


def _paths_from_json(raw: str | None) -> tuple[str, ...]:
    if not raw:
        return ()
    loaded = json.loads(raw)
    if not isinstance(loaded, list):
        return ()
    return tuple(str(path) for path in loaded if isinstance(path, str))


def _message_ids_from_json(raw: str | None) -> tuple[int, ...]:
    if not raw:
        return ()
    loaded = json.loads(raw)
    if not isinstance(loaded, list):
        return ()
    return tuple(int(message_id) for message_id in loaded if isinstance(message_id, int))


def _json_or_none(value: dict[str, object] | None) -> str | None:
    if value is None:
        return None
    return json.dumps(value, sort_keys=True)


def _reply_markup_from_json(raw: str | None) -> dict[str, object] | None:
    if not raw:
        return None
    loaded = json.loads(raw)
    if not isinstance(loaded, dict):
        return None
    return loaded
