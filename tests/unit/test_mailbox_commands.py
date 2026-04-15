from codex_telegram_gateway.mailbox_commands import (
    MailboxCommand,
    MailboxPeer,
    parse_mailbox_command,
    render_mailbox_delivery_text,
    render_mailbox_help,
    render_mailbox_peers,
    render_mailbox_recipient_notice,
    render_mailbox_send_ack,
)


def test_parse_mailbox_command_send_with_recipient_and_body() -> None:
    assert parse_mailbox_command("send thread-2 Please review the latest patch.") == MailboxCommand(
        action="send",
        recipient_thread_id="thread-2",
        body="Please review the latest patch.",
    )


def test_render_mailbox_help_lists_supported_subcommands() -> None:
    assert render_mailbox_help() == (
        "Inter-agent mailbox commands:\n"
        "/gateway msg peers - List bound peer threads\n"
        "/gateway msg send <thread-id> <body> - Queue a mailbox message to another thread\n"
        "/gateway msg inbox - List mailbox messages for this thread\n"
        "/gateway msg read <message-id> - Show and mark a mailbox message as read\n"
        "/gateway msg reply <message-id> <body> - Reply to a mailbox message\n"
        "/gateway msg broadcast <body> - Broadcast a mailbox message to other peer threads"
    )


def test_render_mailbox_delivery_text_formats_sender_context() -> None:
    assert render_mailbox_delivery_text(
        message_id="mail-1",
        sender_title="thread-1",
        sender_project_name="gateway-project",
        body="Please review the latest patch.",
    ) == "[Mailbox `mail-1` from `thread-1` · gateway-project]\nPlease review the latest patch."


def test_render_mailbox_ack_and_recipient_notice() -> None:
    assert render_mailbox_send_ack(message_id="mail-1", recipient_title="thread-2") == (
        "Queued mailbox message `mail-1` to `thread-2`."
    )
    assert render_mailbox_recipient_notice(message_id="mail-1", sender_title="thread-1") == (
        "Mailbox message `mail-1` queued from `thread-1`."
    )


def test_render_mailbox_peers_marks_current_thread() -> None:
    assert render_mailbox_peers(
        [
            MailboxPeer(
                thread_id="thread-1",
                title="thread-1",
                project_name="gateway-project",
                status="idle",
                is_current=True,
            ),
            MailboxPeer(
                thread_id="thread-2",
                title="thread-2",
                project_name="gateway-project",
                status="running",
            ),
        ]
    ) == (
        "Bound peer threads:\n"
        "- `thread-1` · gateway-project · idle · current topic\n"
        "- `thread-2` · gateway-project · running"
    )


def test_parse_mailbox_command_defaults_to_help_for_empty_or_unknown_input() -> None:
    assert parse_mailbox_command("") == MailboxCommand(action="help")
    assert parse_mailbox_command("nonsense") == MailboxCommand(action="help")


def test_render_mailbox_peers_handles_empty_list() -> None:
    assert render_mailbox_peers([]) == "Bound peer threads:\n- No other bound peer threads right now"
