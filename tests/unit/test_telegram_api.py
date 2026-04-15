from pathlib import Path

from codex_telegram_gateway.telegram_api import TelegramApiError, TelegramBotClient, is_missing_topic_error


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


def test_is_missing_topic_error_matches_lifecycle_errors() -> None:
    assert is_missing_topic_error(TelegramApiError("Topic closed")) is True
    assert is_missing_topic_error(TelegramApiError("message thread not found")) is True
    assert is_missing_topic_error(TelegramApiError("some other telegram error")) is False
