from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class MailboxCommand:
    action: str
    recipient_thread_id: str | None = None
    message_id: str | None = None
    body: str = ""


@dataclass(frozen=True)
class MailboxPeer:
    thread_id: str
    title: str
    project_name: str
    status: str
    is_current: bool = False


def parse_mailbox_command(command_args: str) -> MailboxCommand:
    """Parse the `/gateway msg ...` subcommand string."""
    normalized = command_args.strip()
    if not normalized:
        return MailboxCommand(action="help")
    action, _, remainder = normalized.partition(" ")
    action = action.lower()
    remainder = remainder.strip()
    if action in {"help", "peers", "inbox"}:
        return MailboxCommand(action=action)
    if action == "read":
        return MailboxCommand(action=action, message_id=remainder or None)
    if action == "broadcast":
        return MailboxCommand(action=action, body=remainder)
    if action in {"send", "reply"}:
        target, _, body = remainder.partition(" ")
        return MailboxCommand(
            action=action,
            recipient_thread_id=(target or None) if action == "send" else None,
            message_id=(target or None) if action == "reply" else None,
            body=body.strip(),
        )
    return MailboxCommand(action="help")


def render_mailbox_help() -> str:
    """Render operator help for the mailbox command family."""
    return "\n".join(
        [
            "Inter-agent mailbox commands:",
            "/gateway msg peers - List bound peer threads",
            "/gateway msg send <thread-id> <body> - Queue a mailbox message to another thread",
            "/gateway msg inbox - List mailbox messages for this thread",
            "/gateway msg read <message-id> - Show and mark a mailbox message as read",
            "/gateway msg reply <message-id> <body> - Reply to a mailbox message",
            "/gateway msg broadcast <body> - Broadcast a mailbox message to other peer threads",
        ]
    )


def render_mailbox_delivery_text(
    *,
    message_id: str,
    sender_title: str,
    sender_project_name: str,
    body: str,
) -> str:
    """Render the text injected into the recipient Codex thread."""
    return f"[Mailbox `{message_id}` from `{sender_title}` · {sender_project_name}]\n{body.strip()}"


def render_mailbox_send_ack(*, message_id: str, recipient_title: str) -> str:
    """Render the sender-topic acknowledgement after queueing a message."""
    return f"Queued mailbox message `{message_id}` to `{recipient_title}`."


def render_mailbox_recipient_notice(*, message_id: str, sender_title: str) -> str:
    """Render the recipient-topic notification for a queued mailbox message."""
    return f"Mailbox message `{message_id}` queued from `{sender_title}`."


def render_mailbox_peers(peers: Sequence[MailboxPeer]) -> str:
    """Render a concise peer list for `/gateway msg peers`."""
    if not peers:
        return "Bound peer threads:\n- No other bound peer threads right now"
    lines = ["Bound peer threads:"]
    for peer in peers:
        line = f"- `{peer.title}` · {peer.project_name} · {peer.status}"
        if peer.is_current:
            line = f"{line} · current topic"
        lines.append(line)
    return "\n".join(lines)
