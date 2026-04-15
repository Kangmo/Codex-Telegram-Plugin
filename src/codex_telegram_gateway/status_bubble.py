from dataclasses import dataclass


@dataclass(frozen=True)
class StatusBubbleSnapshot:
    project_name: str
    thread_title: str
    state: str
    queued_count: int
    latest_summary: str
    history_labels: tuple[str, ...] = ()
    remote_action_rows: tuple[tuple[dict[str, str], ...], ...] = ()


def build_status_bubble(snapshot: StatusBubbleSnapshot) -> tuple[str, dict[str, object]]:
    text = (
        "Topic status\n\n"
        f"Project: `{snapshot.project_name}`\n"
        f"Thread: `{snapshot.thread_title}`\n"
        f"State: `{snapshot.state}`\n"
        f"Queued: `{snapshot.queued_count}`\n"
        f"Latest: {snapshot.latest_summary}"
    )
    rows: list[list[dict[str, str]]] = [
        [{"text": _status_label(snapshot.state), "callback_data": "gw:resp:noop"}]
    ]
    if snapshot.history_labels:
        rows.append(
            [
                {
                    "text": f"↑ {label}",
                    "callback_data": f"gw:resp:recall:{index}",
                }
                for index, label in enumerate(snapshot.history_labels[:2])
            ]
        )
    rows.extend([list(row) for row in snapshot.remote_action_rows])
    rows.append(
        [
            {"text": "↺ New", "callback_data": "gw:resp:new"},
            {"text": "📁 Project", "callback_data": "gw:resp:project"},
            {"text": "📍 Status", "callback_data": "gw:resp:status"},
            {"text": "🔄 Sync", "callback_data": "gw:resp:sync"},
        ]
    )
    return text, {"inline_keyboard": rows}


def _status_label(state: str) -> str:
    if state == "running":
        return "⏳ Working"
    if state == "approval":
        return "⚠ Waiting For Approval"
    if state == "failed":
        return "⚠ Turn Failed"
    if state == "closed":
        return "⚫ Closed"
    return "✓ Ready"
