from pathlib import Path

from codex_telegram_gateway.telegram_api import TelegramBotClient


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
