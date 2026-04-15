from dataclasses import dataclass


ACTIVE_BINDING_STATUS = "active"
CLOSED_BINDING_STATUS = "closed"
DELETED_BINDING_STATUS = "deleted"
ORPHANED_BINDING_STATUS = "orphaned"


@dataclass(frozen=True)
class Binding:
    """Maps one Codex thread id to one persisted Telegram topic id."""

    codex_thread_id: str
    chat_id: int
    message_thread_id: int
    topic_name: str | None
    sync_mode: str
    project_id: str | None = None
    binding_status: str = ACTIVE_BINDING_STATUS


@dataclass(frozen=True)
class CodexProject:
    """One Codex app project identified by its absolute folder path."""

    project_id: str
    project_name: str


@dataclass(frozen=True)
class TopicProject:
    """Pending Telegram topic setup state before a topic is bound to a thread."""

    chat_id: int
    message_thread_id: int
    topic_name: str | None
    project_id: str | None
    picker_message_id: int | None
    pending_update_id: int | None = None
    pending_user_id: int | None = None
    pending_text: str | None = None
    pending_local_image_paths: tuple[str, ...] = ()
    browse_path: str | None = None
    browse_page: int = 0


@dataclass(frozen=True)
class CodexThread:
    """Minimal Codex thread metadata used by the gateway."""

    thread_id: str
    title: str
    status: str
    cwd: str = ""


@dataclass(frozen=True)
class CodexEvent:
    """Normalized outbound Codex event."""

    event_id: str
    thread_id: str
    kind: str
    text: str


@dataclass(frozen=True)
class OutboundMessage:
    """Persisted Telegram message ids for one Codex assistant message block."""

    codex_thread_id: str
    event_id: str
    telegram_message_ids: tuple[int, ...]
    text: str
    reply_markup: dict[str, object] | None = None


@dataclass(frozen=True)
class StartedTurn:
    """Telegram content that should be submitted into a Codex thread."""

    thread_id: str
    text: str = ""
    local_image_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class TurnResult:
    """Normalized result for a Codex turn started by the gateway."""

    turn_id: str
    status: str
    waiting_for_approval: bool = False


@dataclass(frozen=True)
class PendingTurn:
    """A Codex turn that should keep Telegram in a pending state."""

    codex_thread_id: str
    chat_id: int
    message_thread_id: int
    turn_id: str
    waiting_for_approval: bool = False


@dataclass(frozen=True)
class TopicLifecycle:
    """Persisted lifecycle timestamps for one bound Telegram topic."""

    codex_thread_id: str
    chat_id: int
    message_thread_id: int
    bound_at: float | None = None
    last_inbound_at: float | None = None
    last_outbound_at: float | None = None
    completed_at: float | None = None


@dataclass(frozen=True)
class TopicCreationJob:
    """Pending mirror-topic creation work with persisted retry timing."""

    codex_thread_id: str
    chat_id: int
    topic_name: str
    project_id: str | None = None
    retry_after_at: float | None = None


@dataclass(frozen=True)
class InboundMessage:
    """Authorized inbound Telegram content bound to one Codex thread."""

    telegram_update_id: int
    chat_id: int
    message_thread_id: int
    from_user_id: int
    codex_thread_id: str
    text: str = ""
    local_image_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class TopicHistoryEntry:
    """One recent Telegram input kept for ccgram-style recall buttons."""

    text: str = ""
    local_image_paths: tuple[str, ...] = ()
