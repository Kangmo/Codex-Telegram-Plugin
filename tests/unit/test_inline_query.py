from codex_telegram_gateway.inline_query import build_inline_query_results


def test_build_inline_query_results_returns_echo_and_matching_command_suggestions() -> None:
    results = build_inline_query_results(
        "sta",
        passthrough_commands=("status", "model"),
    )

    assert results[0]["type"] == "article"
    assert results[0]["title"] == "sta"
    assert results[0]["input_message_content"] == {"message_text": "sta"}
    inserted_texts = [result["input_message_content"]["message_text"] for result in results]
    assert "/gateway status" in inserted_texts
    assert "/status" in inserted_texts
    assert "/model" not in inserted_texts


def test_build_inline_query_results_returns_no_results_for_blank_query() -> None:
    assert build_inline_query_results("   ", passthrough_commands=("status",)) == []


def test_build_inline_query_results_skips_duplicate_echo_and_caps_results() -> None:
    results = build_inline_query_results(
        "/status",
        passthrough_commands=(
            "status",
            "status_1",
            "status_2",
            "status_3",
            "status_4",
            "status_5",
            "status_6",
            "status_7",
            "status_8",
        ),
    )

    inserted_texts = [result["input_message_content"]["message_text"] for result in results]
    assert inserted_texts[0] == "/status"
    assert inserted_texts.count("/status") == 1
    assert len(results) == 8


def test_build_inline_query_results_treats_slash_only_query_as_match_all() -> None:
    results = build_inline_query_results("/", passthrough_commands=("status",))

    inserted_texts = [result["input_message_content"]["message_text"] for result in results]
    assert inserted_texts[0] == "/"
    assert "/gateway status" in inserted_texts
    assert "/status" in inserted_texts
