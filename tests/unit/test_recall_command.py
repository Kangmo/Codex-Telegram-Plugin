from codex_telegram_gateway.models import TopicHistoryEntry
from codex_telegram_gateway.recall_command import INLINE_QUERY_MAX, history_entry_label, render_recall_prompt


def test_history_entry_label_includes_image_count_and_truncates() -> None:
    label = history_entry_label(
        TopicHistoryEntry(
            text="This is a very long prompt that should be shortened for button labels",
            local_image_paths=("/tmp/example.png",),
        ),
        limit=24,
    )

    assert "…" in label
    assert "[1 image]" in label


def test_render_recall_prompt_uses_inline_query_for_text_and_callback_for_image_entries() -> None:
    text_only = TopicHistoryEntry(text="Please continue with the refactor.")
    with_images = TopicHistoryEntry(
        text="Please inspect the screenshots.",
        local_image_paths=("/tmp/one.png", "/tmp/two.png"),
    )

    text, reply_markup = render_recall_prompt([text_only, with_images])

    assert text.startswith("Recent topic messages")
    assert reply_markup == {
        "inline_keyboard": [
            [
                {
                    "text": "↑ Please continue with the refactor.",
                    "switch_inline_query_current_chat": "Please continue with the refactor.",
                }
            ],
            [
                {
                    "text": "↑ Please inspect the screenshots. [2 images]",
                    "callback_data": "gw:resp:recall:1",
                }
            ],
            [{"text": "Close", "callback_data": "gw:recall:dismiss"}],
        ]
    }


def test_render_recall_prompt_caps_inline_query_text_length() -> None:
    long_text = "a" * (INLINE_QUERY_MAX + 20)

    _, reply_markup = render_recall_prompt([TopicHistoryEntry(text=long_text)])

    assert (
        reply_markup["inline_keyboard"][0][0]["switch_inline_query_current_chat"]
        == "a" * INLINE_QUERY_MAX
    )
