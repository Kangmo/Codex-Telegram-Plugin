import pytest

from codex_telegram_gateway.notification_modes import (
    build_verbose_picker,
    normalize_notification_mode,
    parse_verbose_callback,
    should_emit_notification,
)


def test_normalize_notification_mode_accepts_legacy_aliases() -> None:
    assert normalize_notification_mode("all") == "all"
    assert normalize_notification_mode("assistant_plus_alerts") == "all"
    assert normalize_notification_mode("assistant_only") == "important"
    assert normalize_notification_mode("errors_only") == "errors_only"
    assert normalize_notification_mode("muted") == "muted"


def test_normalize_notification_mode_rejects_invalid_values() -> None:
    with pytest.raises(ValueError, match="Invalid notification mode"):
        normalize_notification_mode("noisy")


def test_build_verbose_picker_renders_all_modes_and_marks_current_choice() -> None:
    text, markup = build_verbose_picker("assistant_plus_alerts")

    assert text == (
        "Notification mode\n\n"
        "Current: `all`\n\n"
        "- `all`: typing and routine status chatter\n"
        "- `important`: only important alerts and errors\n"
        "- `errors_only`: only errors\n"
        "- `muted`: suppress supplemental chatter"
    )
    assert markup == {
        "inline_keyboard": [
            [{"text": "✓ Bell All", "callback_data": "gw:verbose:set:all"}],
            [{"text": "Mention Important", "callback_data": "gw:verbose:set:important"}],
            [{"text": "Warning Errors Only", "callback_data": "gw:verbose:set:errors_only"}],
            [{"text": "Silent Muted", "callback_data": "gw:verbose:set:muted"}],
            [{"text": "Dismiss", "callback_data": "gw:verbose:dismiss"}],
        ]
    }


def test_parse_verbose_callback_understands_set_and_dismiss() -> None:
    assert parse_verbose_callback("gw:verbose:set:important") == {
        "action": "set",
        "mode": "important",
    }
    assert parse_verbose_callback("gw:verbose:dismiss") == {
        "action": "dismiss",
        "mode": None,
    }
    assert parse_verbose_callback("gw:verbose:set:assistant_plus_alerts") == {
        "action": "set",
        "mode": "all",
    }
    assert parse_verbose_callback("gw:verbose:set:broken") is None


@pytest.mark.parametrize(
    ("mode", "kind", "expected"),
    [
        ("all", "typing", True),
        ("all", "info", True),
        ("all", "important", True),
        ("all", "error", True),
        ("important", "typing", False),
        ("important", "info", False),
        ("important", "important", True),
        ("important", "error", True),
        ("errors_only", "typing", False),
        ("errors_only", "important", False),
        ("errors_only", "error", True),
        ("muted", "typing", False),
        ("muted", "info", False),
        ("muted", "important", False),
        ("muted", "error", True),
    ],
)
def test_should_emit_notification_uses_mode_matrix(mode: str, kind: str, expected: bool) -> None:
    assert should_emit_notification(mode, kind) is expected
