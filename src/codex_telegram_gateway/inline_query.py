"""Telegram inline-query helpers for safe text insertion into the current chat."""

from __future__ import annotations


_ECHO_DESCRIPTION = "Tap to insert into the current chat."
_MAX_RESULTS = 8
_GATEWAY_COMMANDS: tuple[tuple[str, str], ...] = (
    ("/gateway status", "Show the current topic binding and Codex thread status."),
    ("/gateway recall", "Recall recent topic messages."),
    ("/gateway bindings", "Open the sessions dashboard."),
    ("/gateway create_thread", "Start a fresh Codex thread in this topic."),
    ("/gateway project", "Open the project picker for this topic."),
    ("/gateway sync", "Audit bindings and recover missing topics."),
    ("/gateway help", "Show available gateway commands."),
)


def build_inline_query_results(
    query: str,
    *,
    passthrough_commands: tuple[str, ...] = (),
) -> list[dict[str, object]]:
    normalized_query = " ".join(query.split()).strip()
    if not normalized_query:
        return []

    results: list[dict[str, object]] = [
        _article_result(
            result_id="echo",
            title=normalized_query,
            description=_ECHO_DESCRIPTION,
            message_text=normalized_query,
        )
    ]

    seen_message_texts = {normalized_query}
    query_key = normalized_query.lstrip("/").lower()
    for command_text, description in _command_candidates(passthrough_commands):
        if not _matches_query(query_key, command_text, description):
            continue
        if command_text in seen_message_texts:
            continue
        seen_message_texts.add(command_text)
        results.append(
            _article_result(
                result_id=f"cmd:{len(results)}",
                title=command_text,
                description=description,
                message_text=command_text,
            )
        )
        if len(results) >= _MAX_RESULTS:
            break
    return results


def _command_candidates(passthrough_commands: tuple[str, ...]) -> tuple[tuple[str, str], ...]:
    passthrough_results = tuple(
        (
            f"/{command_name}",
            "Pass through to the bound Codex thread.",
        )
        for command_name in passthrough_commands
    )
    return (*passthrough_results, *_GATEWAY_COMMANDS)


def _matches_query(query_key: str, command_text: str, description: str) -> bool:
    if not query_key:
        return True
    return query_key in command_text.lstrip("/").lower() or query_key in description.lower()


def _article_result(
    *,
    result_id: str,
    title: str,
    description: str,
    message_text: str,
) -> dict[str, object]:
    return {
        "type": "article",
        "id": result_id,
        "title": title,
        "description": description,
        "input_message_content": {"message_text": message_text},
    }
