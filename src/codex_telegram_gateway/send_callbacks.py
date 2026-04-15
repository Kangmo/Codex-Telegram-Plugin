_SEND_PREFIX = "gw:send:"


def parse_send_callback(data: str) -> dict[str, int | str | None] | None:
    if not data.startswith(_SEND_PREFIX):
        return None
    payload = data[len(_SEND_PREFIX) :]
    if payload in {"back", "root", "cancel", "doc", "photo"}:
        return {"action": payload, "index": None}
    parts = payload.split(":")
    if len(parts) != 2:
        return None
    action, raw_index = parts
    if action not in {"page", "enter", "preview"}:
        return None
    try:
        index = int(raw_index)
    except ValueError:
        return None
    if index < 0:
        return None
    return {"action": action, "index": index}
