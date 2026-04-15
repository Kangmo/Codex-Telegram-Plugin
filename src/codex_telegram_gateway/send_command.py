from codex_telegram_gateway.send_security import SendBrowserListing, SendFilePreview


def build_send_browser_page(
    *,
    project_name: str,
    listing: SendBrowserListing,
) -> tuple[str, dict[str, object]]:
    current_label = listing.current_relative_path or "."
    if listing.query:
        text = (
            f"Send file from `{project_name}`\n\n"
            f"Search: `{listing.query}`\n"
            "Tap a folder to enter or a file to preview."
        )
    else:
        text = (
            f"Send file from `{project_name}`\n\n"
            f"Current: `{current_label}`\n"
            "Tap a folder to enter or a file to preview."
        )

    rows: list[list[dict[str, str]]] = []
    for index, entry in enumerate(listing.entries):
        icon = "📁" if entry.is_dir else "📄"
        action = "enter" if entry.is_dir else "preview"
        rows.append([{"text": f"{icon} {entry.name}", "callback_data": f"gw:send:{action}:{index}"}])

    nav_row: list[dict[str, str]] = []
    if listing.page_index > 0:
        nav_row.append({"text": "Prev", "callback_data": f"gw:send:page:{listing.page_index - 1}"})
    if listing.page_index + 1 < listing.total_pages:
        nav_row.append({"text": "Next", "callback_data": f"gw:send:page:{listing.page_index + 1}"})
    if nav_row:
        rows.append(nav_row)

    action_row: list[dict[str, str]] = []
    if listing.current_relative_path not in {"", "."} and listing.query is None:
        action_row.append({"text": "..", "callback_data": "gw:send:back"})
    action_row.append({"text": "Root", "callback_data": "gw:send:root"})
    action_row.append({"text": "Cancel", "callback_data": "gw:send:cancel"})
    rows.append(action_row)
    return text, {"inline_keyboard": rows}


def build_send_preview_page(
    *,
    project_name: str,
    preview: SendFilePreview,
) -> tuple[str, dict[str, object]]:
    text = (
        f"Send file from `{project_name}`\n\n"
        f"Path: `{preview.relative_path}`\n"
        f"Type: `{preview.mime_type}`\n"
        f"Size: `{_format_size_bytes(preview.size_bytes)}`\n\n"
        "Choose how to send this file."
    )
    first_row = (
        [
            {"text": "Send Photo", "callback_data": "gw:send:photo"},
            {"text": "Send Document", "callback_data": "gw:send:doc"},
        ]
        if preview.send_as_photo
        else [{"text": "Send Document", "callback_data": "gw:send:doc"}]
    )
    return text, {
        "inline_keyboard": [
            first_row,
            [
                {"text": "Back", "callback_data": "gw:send:back"},
                {"text": "Cancel", "callback_data": "gw:send:cancel"},
            ],
        ]
    }


def _format_size_bytes(size_bytes: int) -> str:
    return f"{size_bytes} B"
