import io
from pathlib import Path
from urllib import error

import pytest

from codex_telegram_gateway.telegram_api import (
    TelegramApiError,
    TelegramBotClient,
    TelegramRetryAfterError,
    _document_media_kind,
    _generated_attachment_name,
    _unsupported_content_kind,
    is_missing_topic_error,
    is_topic_edit_permission_error,
)


class StubTelegramBotClient(TelegramBotClient):
    def __init__(self, updates: list[dict[str, object]]) -> None:
        super().__init__("test-token")
        self._updates = updates

    def _call(self, method: str, payload: dict[str, object]) -> dict[str, object] | list[object]:
        del payload
        if method == "getUpdates":
            return self._updates
        if method == "getFile":
            return {"file_path": "photos/example-file.jpg"}
        raise AssertionError(f"Unexpected Telegram API method: {method}")

    def _download_file(self, file_path: str, destination: Path) -> None:
        assert file_path == "photos/example-file.jpg"
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"jpeg-bytes")


class RecordingTelegramBotClient(TelegramBotClient):
    def __init__(self) -> None:
        super().__init__("test-token")
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.multipart_calls: list[tuple[str, dict[str, object], str, Path]] = []

    def _call(self, method: str, payload: dict[str, object]) -> dict[str, object] | list[object]:
        self.calls.append((method, payload))
        return {}

    def _call_multipart(
        self,
        method: str,
        payload: dict[str, object],
        *,
        file_field_name: str,
        file_path: Path,
    ) -> dict[str, object] | list[object]:
        self.multipart_calls.append((method, payload, file_field_name, file_path))
        return {"message_id": 42}


class BrokenMultipartTelegramBotClient(TelegramBotClient):
    def __init__(self) -> None:
        super().__init__("test-token")

    def _call(self, method: str, payload: dict[str, object]) -> dict[str, object] | list[object]:
        raise AssertionError(f"Unexpected Telegram API method: {method} {payload}")

    def _call_multipart(
        self,
        method: str,
        payload: dict[str, object],
        *,
        file_field_name: str,
        file_path: Path,
    ) -> dict[str, object] | list[object]:
        del method, payload, file_field_name, file_path
        return {}


def test_get_updates_downloads_photo_and_returns_local_image_path(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = StubTelegramBotClient(
        [
            {
                "update_id": 1,
                "message": {
                    "message_id": 99,
                    "message_thread_id": 77,
                    "chat": {"id": -100100},
                    "from": {"id": 111},
                    "caption": "Please inspect this screenshot.",
                    "photo": [
                        {
                            "file_id": "file-1",
                            "file_unique_id": "unique-1",
                            "file_size": 1234,
                        }
                    ],
                },
            }
        ]
    )

    updates = client.get_updates()

    assert len(updates) == 1
    assert updates[0]["kind"] == "message"
    assert updates[0]["text"] == "Please inspect this screenshot."
    assert updates[0]["local_image_paths"]
    image_path = Path(updates[0]["local_image_paths"][0])
    assert image_path.exists()
    assert image_path.parent.name == ".ccgram-uploads"
    assert image_path.suffix == ".jpg"


def test_get_updates_downloads_document_and_returns_prompt_text(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = StubTelegramBotClient(
        [
            {
                "update_id": 2,
                "message": {
                    "message_id": 100,
                    "message_thread_id": 77,
                    "chat": {"id": -100100},
                    "from": {"id": 111},
                    "caption": "Please review the attached PDF.",
                    "document": {
                        "file_id": "file-2",
                        "file_unique_id": "unique-2",
                        "file_name": "design-spec.pdf",
                        "mime_type": "application/pdf",
                        "file_size": 2048,
                    },
                },
            }
        ]
    )

    updates = client.get_updates()

    assert updates == [
        {
            "kind": "message",
            "update_id": 2,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 111,
            "text": (
                "I've uploaded a PDF to "
                f"{tmp_path}/.ccgram-uploads/design-spec.pdf. "
                "Please inspect or read it as needed.\n\n"
                "User note: Please review the attached PDF."
            ),
            "local_image_paths": (),
        }
    ]


def test_get_updates_returns_unsupported_message_for_sticker() -> None:
    client = StubTelegramBotClient(
        [
            {
                "update_id": 4,
                "message": {
                    "message_id": 102,
                    "message_thread_id": 77,
                    "chat": {"id": -100100},
                    "from": {"id": 111},
                    "sticker": {"file_id": "sticker-1"},
                },
            }
        ]
    )

    assert client.get_updates() == [
        {
            "kind": "unsupported_message",
            "update_id": 4,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 111,
            "notice": "⚠ Stickers are not supported yet. Use text, photos, documents, audio, or video.",
        }
    ]


def test_get_updates_downloads_voice_and_returns_voice_message(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = StubTelegramBotClient(
        [
            {
                "update_id": 8,
                "message": {
                    "message_id": 106,
                    "message_thread_id": 77,
                    "chat": {"id": -100100},
                    "from": {"id": 111},
                    "voice": {
                        "file_id": "voice-1",
                        "file_unique_id": "voice-unique-1",
                        "mime_type": "audio/ogg",
                        "file_size": 2048,
                    },
                },
            }
        ]
    )

    updates = client.get_updates()

    assert len(updates) == 1
    assert updates[0]["kind"] == "voice_message"
    assert updates[0]["update_id"] == 8
    assert updates[0]["chat_id"] == -100100
    assert updates[0]["message_thread_id"] == 77
    assert updates[0]["from_user_id"] == 111
    assert str(updates[0]["file_path"]).startswith(f"{tmp_path}/.ccgram-uploads/voice_")
    assert str(updates[0]["file_path"]).endswith(".ogg")


def test_get_updates_returns_inline_query() -> None:
    client = StubTelegramBotClient(
        [
            {
                "update_id": 9,
                "inline_query": {
                    "id": "inline-1",
                    "from": {"id": 111},
                    "query": "sta",
                },
            }
        ]
    )

    assert client.get_updates() == [
        {
            "kind": "inline_query",
            "update_id": 9,
            "inline_query_id": "inline-1",
            "from_user_id": 111,
            "query": "sta",
        }
    ]


def test_get_updates_skips_inline_query_without_sender_or_id() -> None:
    client = StubTelegramBotClient(
        [
            {
                "update_id": 10,
                "inline_query": {
                    "id": "inline-1",
                    "from": None,
                    "query": "sta",
                },
            },
            {
                "update_id": 11,
                "inline_query": {
                    "id": 123,
                    "from": {"id": 111},
                    "query": "sta",
                },
            },
        ]
    )

    assert client.get_updates() == []


def test_get_updates_skips_unsupported_message_without_sender() -> None:
    client = StubTelegramBotClient(
        [
            {
                "update_id": 5,
                "message": {
                    "message_id": 103,
                    "message_thread_id": 77,
                    "chat": {"id": -100100},
                    "from": None,
                    "sticker": {"file_id": "sticker-1"},
                },
            }
        ]
    )

    assert client.get_updates() == []


def test_get_updates_downloads_audio_and_video_and_generates_prompt_texts(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = StubTelegramBotClient(
        [
            {
                "update_id": 6,
                "message": {
                    "message_id": 104,
                    "message_thread_id": 77,
                    "chat": {"id": -100100},
                    "from": {"id": 111},
                    "caption": "Audio context",
                    "audio": {
                        "file_id": "audio-1",
                        "file_unique_id": "audio-unique-1",
                        "file_name": "briefing.mp3",
                        "mime_type": "audio/mpeg",
                        "file_size": 1024,
                    },
                },
            },
            {
                "update_id": 7,
                "message": {
                    "message_id": 105,
                    "message_thread_id": 78,
                    "chat": {"id": -100100},
                    "from": {"id": 111},
                    "video": {
                        "file_id": "video-1",
                        "file_unique_id": "video-unique-1",
                        "mime_type": "video/mp4",
                        "file_size": 4096,
                    },
                },
            },
        ]
    )

    updates = client.get_updates()

    assert updates[0] == {
        "kind": "message",
        "update_id": 6,
        "chat_id": -100100,
        "message_thread_id": 77,
        "from_user_id": 111,
        "text": (
            "I've uploaded an audio file to "
            f"{tmp_path}/.ccgram-uploads/briefing.mp3. "
            "Please inspect the media file as needed.\n\n"
            "User note: Audio context"
        ),
        "local_image_paths": (),
    }
    assert updates[1]["kind"] == "message"
    assert updates[1]["update_id"] == 7
    assert updates[1]["message_thread_id"] == 78
    assert updates[1]["from_user_id"] == 111
    assert updates[1]["local_image_paths"] == ()
    assert updates[1]["text"].startswith(
        "I've uploaded a video file to "
        f"{tmp_path}/.ccgram-uploads/video_"
    )
    assert updates[1]["text"].endswith(".mp4. Please inspect the media file as needed.")


def test_extract_saved_attachment_returns_none_without_file_id(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    client = StubTelegramBotClient([])

    assert client._extract_saved_attachment({"document": {"file_name": "notes.txt"}}) is None
    assert client._download_generic_attachment({}, prefix="audio", media_kind="audio") is None


def test_document_media_kind_generated_name_and_unsupported_kind_helpers() -> None:
    assert _document_media_kind({"mime_type": "text/plain"}) == "text"
    assert _document_media_kind({"file_name": "notes.md"}) == "text"
    assert _document_media_kind({"file_name": "archive.bin"}) == "document"

    generated_name = _generated_attachment_name(
        "video",
        {
            "file_unique_id": "unique-video",
            "mime_type": "video/mp4",
        },
    )
    assert generated_name.startswith("video_")
    assert generated_name.endswith("_unique-v.mp4")

    assert _unsupported_content_kind({"voice": {"file_id": "voice-1"}}) is None
    assert _unsupported_content_kind({"animation": {}}) == "generic"
    assert _unsupported_content_kind({"text": "hello"}) is None


def test_get_updates_normalizes_topic_closed_and_reopened_events() -> None:
    client = StubTelegramBotClient(
        [
            {
                "update_id": 1,
                "message": {
                    "message_id": 99,
                    "message_thread_id": 77,
                    "chat": {"id": -100100},
                    "from": {"id": 111},
                    "forum_topic_closed": True,
                },
            },
            {
                "update_id": 2,
                "message": {
                    "message_id": 100,
                    "message_thread_id": 77,
                    "chat": {"id": -100100},
                    "from": {"id": 111},
                    "forum_topic_reopened": True,
                },
            },
        ]
    )

    assert client.get_updates() == [
        {
            "kind": "topic_closed",
            "update_id": 1,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 111,
        },
        {
            "kind": "topic_reopened",
            "update_id": 2,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 111,
        },
    ]


def test_get_updates_normalizes_topic_edited_events() -> None:
    client = StubTelegramBotClient(
        [
            {
                "update_id": 3,
                "message": {
                    "message_id": 101,
                    "message_thread_id": 77,
                    "chat": {"id": -100100},
                    "from": {"id": 111},
                    "forum_topic_edited": {"name": "(gateway-project) renamed"},
                },
            }
        ]
    )

    assert client.get_updates() == [
        {
            "kind": "topic_edited",
            "update_id": 3,
            "chat_id": -100100,
            "message_thread_id": 77,
            "from_user_id": 111,
            "topic_name": "(gateway-project) renamed",
        }
    ]


def test_is_missing_topic_error_matches_lifecycle_errors() -> None:
    assert is_missing_topic_error(TelegramApiError("Topic closed")) is True
    assert is_missing_topic_error(TelegramApiError("message thread not found")) is True
    assert is_missing_topic_error(TelegramApiError("some other telegram error")) is False


def test_is_topic_edit_permission_error_matches_admin_rights_failures() -> None:
    assert is_topic_edit_permission_error(TelegramApiError("Not enough rights to manage topics")) is True
    assert is_topic_edit_permission_error(TelegramApiError("CHAT_ADMIN_REQUIRED")) is True
    assert is_topic_edit_permission_error(TelegramApiError("some other telegram error")) is False


def test_close_forum_topic_calls_telegram_api() -> None:
    client = RecordingTelegramBotClient()

    client.close_forum_topic(-100100, 77)

    assert client.calls == [
        (
            "closeForumTopic",
            {
                "chat_id": -100100,
                "message_thread_id": 77,
            },
        )
    ]


def test_delete_forum_topic_calls_telegram_api() -> None:
    client = RecordingTelegramBotClient()

    client.delete_forum_topic(-100100, 77)

    assert client.calls == [
        (
            "deleteForumTopic",
            {
                "chat_id": -100100,
                "message_thread_id": 77,
            },
        )
    ]


def test_send_document_file_calls_telegram_api_with_multipart_upload(tmp_path) -> None:
    client = RecordingTelegramBotClient()
    file_path = tmp_path / "notes.txt"
    file_path.write_text("notes")

    message_id = client.send_document_file(-100100, 77, file_path, caption="notes.txt")

    assert message_id == 42
    assert client.multipart_calls == [
        (
            "sendDocument",
            {
                "chat_id": -100100,
                "message_thread_id": 77,
                "caption": "notes.txt",
            },
            "document",
            file_path,
        )
    ]


def test_answer_inline_query_serializes_results() -> None:
    client = RecordingTelegramBotClient()

    client.answer_inline_query(
        "inline-1",
        [
            {
                "type": "article",
                "id": "echo",
                "title": "sta",
                "description": "Tap to insert into the current chat.",
                "input_message_content": {"message_text": "sta"},
            }
        ],
        cache_time=0,
        is_personal=True,
    )

    assert client.calls == [
        (
            "answerInlineQuery",
            {
                "inline_query_id": "inline-1",
                "results": (
                    '[{"type": "article", "id": "echo", "title": "sta", '
                    '"description": "Tap to insert into the current chat.", '
                    '"input_message_content": {"message_text": "sta"}}]'
                ),
                "cache_time": 0,
                "is_personal": True,
            },
        )
    ]


def test_send_photo_file_calls_telegram_api_with_multipart_upload(tmp_path) -> None:
    client = RecordingTelegramBotClient()
    file_path = tmp_path / "diagram.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    message_id = client.send_photo_file(-100100, 77, file_path, caption="images/diagram.png")

    assert message_id == 42
    assert client.multipart_calls == [
        (
            "sendPhoto",
            {
                "chat_id": -100100,
                "message_thread_id": 77,
                "caption": "images/diagram.png",
            },
            "photo",
            file_path,
        )
    ]


def test_edit_message_photo_file_calls_telegram_api_with_multipart_upload(tmp_path) -> None:
    client = RecordingTelegramBotClient()
    file_path = tmp_path / "live.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    client.edit_message_photo_file(
        -100100,
        42,
        file_path,
        caption="Live view · gateway-project / thread-1",
        reply_markup={"inline_keyboard": [[{"text": "Stop", "callback_data": "gw:live:stop"}]]},
    )

    assert client.multipart_calls == [
        (
            "editMessageMedia",
            {
                "chat_id": -100100,
                "message_id": 42,
                "media": (
                    '{"type": "photo", "media": "attach://photo", "caption": '
                    '"Live view \\u00b7 gateway-project / thread-1"}'
                ),
                "reply_markup": '{"inline_keyboard": [[{"text": "Stop", "callback_data": "gw:live:stop"}]]}',
            },
            "photo",
            file_path,
        )
    ]


def test_edit_message_caption_calls_telegram_api() -> None:
    client = RecordingTelegramBotClient()

    client.edit_message_caption(
        -100100,
        42,
        "Live view · gateway-project / thread-1\nStopped.",
        reply_markup={"inline_keyboard": [[{"text": "Start live", "callback_data": "gw:live:start"}]]},
    )

    assert client.calls == [
        (
            "editMessageCaption",
            {
                "chat_id": -100100,
                "message_id": 42,
                "caption": "Live view · gateway-project / thread-1\nStopped.",
                "reply_markup": '{"inline_keyboard": [[{"text": "Start live", "callback_data": "gw:live:start"}]]}',
            },
        )
    ]


def test_send_document_file_rejects_multipart_responses_without_message_id(tmp_path) -> None:
    client = BrokenMultipartTelegramBotClient()
    file_path = tmp_path / "notes.txt"
    file_path.write_text("notes")

    with pytest.raises(TelegramApiError, match="Unexpected sendDocument response"):
        client.send_document_file(-100100, 77, file_path)


def test_send_photo_file_rejects_multipart_responses_without_message_id(tmp_path) -> None:
    client = BrokenMultipartTelegramBotClient()
    file_path = tmp_path / "diagram.png"
    file_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    with pytest.raises(TelegramApiError, match="Unexpected sendPhoto response"):
        client.send_photo_file(-100100, 77, file_path)


def test_call_multipart_upload_encodes_body_and_returns_result(tmp_path, monkeypatch) -> None:
    client = TelegramBotClient("test-token")
    file_path = tmp_path / "notes.txt"
    file_path.write_text("notes")
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"ok": true, "result": {"message_id": 55}}'

    def fake_urlopen(req, timeout: int):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.header_items())
        captured["body"] = req.data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("codex_telegram_gateway.telegram_api.request.urlopen", fake_urlopen)

    result = client._call_multipart(
        "sendDocument",
        {"chat_id": -100100, "message_thread_id": 77, "caption": "notes.txt"},
        file_field_name="document",
        file_path=file_path,
    )

    assert result == {"message_id": 55}
    assert captured["url"] == "https://api.telegram.org/bottest-token/sendDocument"
    assert captured["timeout"] == 30
    assert "multipart/form-data; boundary=codex-telegram-" in captured["headers"]["Content-type"]
    assert b'name="chat_id"' in captured["body"]
    assert b"-100100" in captured["body"]
    assert b'name="document"; filename="notes.txt"' in captured["body"]
    assert b"notes" in captured["body"]


def test_send_message_uses_default_request_timeout(monkeypatch) -> None:
    client = TelegramBotClient("test-token")
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"ok": true, "result": {"message_id": 55}}'

    def fake_urlopen(req, timeout: int):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("codex_telegram_gateway.telegram_api.request.urlopen", fake_urlopen)

    assert client.send_message(-100100, 77, "hello") == 55
    assert captured["url"] == "https://api.telegram.org/bottest-token/sendMessage"
    assert captured["timeout"] == 10


def test_edit_message_text_uses_short_request_timeout(monkeypatch) -> None:
    client = TelegramBotClient("test-token")
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"ok": true, "result": true}'

    def fake_urlopen(req, timeout: int):
        captured["url"] = req.full_url
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("codex_telegram_gateway.telegram_api.request.urlopen", fake_urlopen)

    client.edit_message_text(-100100, 55, "updated")
    assert captured["url"] == "https://api.telegram.org/bottest-token/editMessageText"
    assert captured["timeout"] == 5


def test_call_multipart_raises_api_error_when_telegram_returns_unsuccessful_result(
    tmp_path,
    monkeypatch,
) -> None:
    client = TelegramBotClient("test-token")
    file_path = tmp_path / "notes.txt"
    file_path.write_text("notes")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

        def read(self) -> bytes:
            return b'{"ok": false, "description": "bad request"}'

    monkeypatch.setattr(
        "codex_telegram_gateway.telegram_api.request.urlopen",
        lambda req, timeout: FakeResponse(),
    )

    with pytest.raises(TelegramApiError, match="Telegram API error for sendDocument"):
        client._call_multipart(
            "sendDocument",
            {"chat_id": -100100, "message_thread_id": 77},
            file_field_name="document",
            file_path=file_path,
        )


def test_call_multipart_raises_http_error_for_non_json_body(tmp_path, monkeypatch) -> None:
    client = TelegramBotClient("test-token")
    file_path = tmp_path / "notes.txt"
    file_path.write_text("notes")

    def fake_urlopen(req, timeout: int):
        del req, timeout
        raise error.HTTPError(
            url="https://api.telegram.org/bottest-token/sendDocument",
            code=400,
            msg="Bad Request",
            hdrs=None,
            fp=io.BytesIO(b"not-json"),
        )

    monkeypatch.setattr("codex_telegram_gateway.telegram_api.request.urlopen", fake_urlopen)

    with pytest.raises(TelegramApiError, match="Telegram HTTP error for sendDocument: not-json"):
        client._call_multipart(
            "sendDocument",
            {"chat_id": -100100, "message_thread_id": 77},
            file_field_name="document",
            file_path=file_path,
        )


def test_call_multipart_raises_request_error_on_url_failure(tmp_path, monkeypatch) -> None:
    client = TelegramBotClient("test-token")
    file_path = tmp_path / "notes.txt"
    file_path.write_text("notes")

    def fake_urlopen(req, timeout: int):
        del req, timeout
        raise error.URLError("offline")

    monkeypatch.setattr("codex_telegram_gateway.telegram_api.request.urlopen", fake_urlopen)

    with pytest.raises(TelegramApiError, match="Telegram request failed for sendDocument"):
        client._call_multipart(
            "sendDocument",
            {"chat_id": -100100, "message_thread_id": 77},
            file_field_name="document",
            file_path=file_path,
        )


def test_raise_api_error_returns_retry_after_error_for_flood_control() -> None:
    try:
        TelegramBotClient._raise_api_error(
            "createForumTopic",
            {
                "ok": False,
                "parameters": {"retry_after": 27},
            },
        )
    except TelegramRetryAfterError as exc:
        assert exc.retry_after_seconds == 27
    else:
        raise AssertionError("Expected TelegramRetryAfterError")
