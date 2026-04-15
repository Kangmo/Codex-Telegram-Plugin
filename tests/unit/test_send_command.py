from codex_telegram_gateway.send_callbacks import parse_send_callback
from codex_telegram_gateway.send_command import (
    build_send_browser_page,
    build_send_preview_page,
)
from codex_telegram_gateway.send_security import SendBrowserEntry, SendBrowserListing, SendFilePreview


def test_build_send_browser_page_renders_entries_and_navigation() -> None:
    text, markup = build_send_browser_page(
        project_name="gateway-project",
        listing=SendBrowserListing(
            project_root="/Users/kangmo/sacle/src/gateway-project",
            current_relative_path="docs",
            entries=(
                SendBrowserEntry(name="designs", relative_path="docs/designs", is_dir=True),
                SendBrowserEntry(name="notes.txt", relative_path="docs/notes.txt", is_dir=False),
            ),
            page_index=0,
            total_pages=2,
            query=None,
        ),
    )

    assert text == (
        "Send file from `gateway-project`\n\n"
        "Current: `docs`\n"
        "Tap a folder to enter or a file to preview."
    )
    assert markup == {
        "inline_keyboard": [
            [{"text": "📁 designs", "callback_data": "gw:send:enter:0"}],
            [{"text": "📄 notes.txt", "callback_data": "gw:send:preview:1"}],
            [{"text": "Next", "callback_data": "gw:send:page:1"}],
            [
                {"text": "..", "callback_data": "gw:send:back"},
                {"text": "Root", "callback_data": "gw:send:root"},
                {"text": "Cancel", "callback_data": "gw:send:cancel"},
            ],
        ]
    }


def test_build_send_preview_page_renders_photo_and_document_actions() -> None:
    text, markup = build_send_preview_page(
        project_name="gateway-project",
        preview=SendFilePreview(
            project_root="/Users/kangmo/sacle/src/gateway-project",
            relative_path="images/diagram.png",
            file_name="diagram.png",
            size_bytes=8,
            mime_type="image/png",
            send_as_photo=True,
        ),
    )

    assert text == (
        "Send file from `gateway-project`\n\n"
        "Path: `images/diagram.png`\n"
        "Type: `image/png`\n"
        "Size: `8 B`\n\n"
        "Choose how to send this file."
    )
    assert markup == {
        "inline_keyboard": [
            [
                {"text": "Send Photo", "callback_data": "gw:send:photo"},
                {"text": "Send Document", "callback_data": "gw:send:doc"},
            ],
            [
                {"text": "Back", "callback_data": "gw:send:back"},
                {"text": "Cancel", "callback_data": "gw:send:cancel"},
            ],
        ]
    }


def test_parse_send_callback_understands_browser_actions() -> None:
    assert parse_send_callback("gw:send:page:2") == {"action": "page", "index": 2}
    assert parse_send_callback("gw:send:enter:1") == {"action": "enter", "index": 1}
    assert parse_send_callback("gw:send:preview:0") == {"action": "preview", "index": 0}
    assert parse_send_callback("gw:send:back") == {"action": "back", "index": None}
    assert parse_send_callback("gw:send:root") == {"action": "root", "index": None}
    assert parse_send_callback("gw:send:cancel") == {"action": "cancel", "index": None}
    assert parse_send_callback("gw:send:doc") == {"action": "doc", "index": None}
    assert parse_send_callback("gw:send:photo") == {"action": "photo", "index": None}


def test_parse_send_callback_rejects_invalid_payloads() -> None:
    assert parse_send_callback("gw:other:page:1") is None
    assert parse_send_callback("gw:send:broken:1") is None
    assert parse_send_callback("gw:send:page:not-a-number") is None
    assert parse_send_callback("gw:send:preview:-1") is None
    assert parse_send_callback("gw:send:page:1:extra") is None
