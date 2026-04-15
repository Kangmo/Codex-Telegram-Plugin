import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request


class TelegramApiError(RuntimeError):
    """Raised when the Telegram Bot API returns an error response."""


_UPLOAD_DIR_NAME = ".ccgram-uploads"
_MAX_FILE_SIZE = 50 * 1024 * 1024
_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9._-]")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_IMAGE_DOCUMENT_EXTENSIONS = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif"}
)


class TelegramBotClient:
    """Thin Telegram Bot API client for topic creation and message sync."""

    def __init__(self, bot_token: str) -> None:
        self._bot_token = bot_token
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    def get_chat(self, chat_id: int) -> dict[str, object]:
        return self._call("getChat", {"chat_id": chat_id})

    def create_forum_topic(self, chat_id: int, name: str) -> int:
        result = self._call("createForumTopic", {"chat_id": chat_id, "name": name[:128]})
        message_thread_id = result.get("message_thread_id")
        if not isinstance(message_thread_id, int):
            raise TelegramApiError(f"Unexpected createForumTopic response: {result}")
        return message_thread_id

    def get_updates(self, offset: int | None = None) -> list[dict[str, object]]:
        payload: dict[str, object] = {"allowed_updates": json.dumps(["message", "callback_query"])}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload)

        updates: list[dict[str, object]] = []
        for update in result:
            callback_query = update.get("callback_query")
            if isinstance(callback_query, dict):
                callback_message = callback_query.get("message")
                sender = callback_query.get("from")
                if not isinstance(callback_message, dict) or not isinstance(sender, dict):
                    continue
                chat = callback_message.get("chat")
                message_thread_id = callback_message.get("message_thread_id")
                message_id = callback_message.get("message_id")
                data = callback_query.get("data")
                if not isinstance(chat, dict):
                    continue
                if not isinstance(message_thread_id, int):
                    continue
                if not isinstance(message_id, int):
                    continue
                if not isinstance(data, str):
                    continue
                updates.append(
                    {
                        "kind": "callback_query",
                        "update_id": int(update["update_id"]),
                        "callback_query_id": str(callback_query["id"]),
                        "chat_id": int(chat["id"]),
                        "message_thread_id": message_thread_id,
                        "message_id": message_id,
                        "from_user_id": int(sender["id"]),
                        "data": data,
                    }
                )
                continue

            message = update.get("message")
            if not isinstance(message, dict):
                continue
            chat = message.get("chat")
            sender = message.get("from")
            message_thread_id = message.get("message_thread_id")
            if not isinstance(chat, dict):
                continue
            if not isinstance(message_thread_id, int):
                continue
            if isinstance(message.get("forum_topic_created"), dict):
                updates.append(
                    {
                        "kind": "topic_created",
                        "update_id": int(update["update_id"]),
                        "chat_id": int(chat["id"]),
                        "message_thread_id": message_thread_id,
                        "from_user_id": int(sender["id"]) if isinstance(sender, dict) else 0,
                        "topic_name": str(message["forum_topic_created"].get("name") or ""),
                    }
                )
                continue
            if message.get("forum_topic_closed") is True:
                updates.append(
                    {
                        "kind": "topic_closed",
                        "update_id": int(update["update_id"]),
                        "chat_id": int(chat["id"]),
                        "message_thread_id": message_thread_id,
                        "from_user_id": int(sender["id"]) if isinstance(sender, dict) else 0,
                    }
                )
                continue
            if message.get("forum_topic_reopened") is True:
                updates.append(
                    {
                        "kind": "topic_reopened",
                        "update_id": int(update["update_id"]),
                        "chat_id": int(chat["id"]),
                        "message_thread_id": message_thread_id,
                        "from_user_id": int(sender["id"]) if isinstance(sender, dict) else 0,
                    }
                )
                continue
            edited_topic = message.get("forum_topic_edited")
            if isinstance(edited_topic, dict):
                updates.append(
                    {
                        "kind": "topic_edited",
                        "update_id": int(update["update_id"]),
                        "chat_id": int(chat["id"]),
                        "message_thread_id": message_thread_id,
                        "from_user_id": int(sender["id"]) if isinstance(sender, dict) else 0,
                        "topic_name": str(edited_topic.get("name") or ""),
                    }
                )
                continue
            text = message.get("text")
            caption = message.get("caption")
            local_image_paths = self._extract_local_image_paths(message)
            normalized_text = text if isinstance(text, str) else ""
            if not normalized_text and isinstance(caption, str):
                normalized_text = _sanitize_caption(caption)
            if not normalized_text and not local_image_paths:
                continue
            if not isinstance(sender, dict):
                continue
            updates.append(
                {
                    "kind": "message",
                    "update_id": int(update["update_id"]),
                    "chat_id": int(chat["id"]),
                    "message_thread_id": message_thread_id,
                    "from_user_id": int(sender["id"]),
                    "text": normalized_text,
                    "local_image_paths": local_image_paths,
                }
            )
        return updates

    def send_message(
        self,
        chat_id: int,
        message_thread_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> int:
        last_message_id: int | None = None
        for part in _split_message(text):
            payload: dict[str, object] = {
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "text": part,
            }
            if reply_markup is not None:
                payload["reply_markup"] = json.dumps(reply_markup)
            result = self._call(
                "sendMessage",
                payload,
            )
            message_id = result.get("message_id")
            if not isinstance(message_id, int):
                raise TelegramApiError(f"Unexpected sendMessage response: {result}")
            last_message_id = message_id
        if last_message_id is None:
            raise TelegramApiError("sendMessage produced no message id.")
        return last_message_id

    def send_chat_action(self, chat_id: int, message_thread_id: int, action: str) -> None:
        self._call(
            "sendChatAction",
            {
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "action": action,
            },
        )

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, object] = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
        self._call("answerCallbackQuery", payload)

    def edit_message_reply_markup(
        self,
        chat_id: int,
        message_id: int,
        reply_markup: dict[str, object] | None,
    ) -> None:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "message_id": message_id,
        }
        if reply_markup is not None:
            payload["reply_markup"] = json.dumps(reply_markup)
        self._call("editMessageReplyMarkup", payload)

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "text": text,
        }
        if reply_markup is not None:
            payload["reply_markup"] = json.dumps(reply_markup)
        self._call("editMessageText", payload)

    def edit_forum_topic(self, chat_id: int, message_thread_id: int, name: str) -> None:
        self._call(
            "editForumTopic",
            {
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "name": name[:128],
            },
        )

    def probe_topic(self, chat_id: int, message_thread_id: int) -> bool:
        try:
            result = self._call(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "message_thread_id": message_thread_id,
                    "text": "\u200b",
                    "disable_notification": True,
                },
            )
        except TelegramApiError as exc:
            if is_missing_topic_error(exc):
                return False
            raise

        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise TelegramApiError(f"Unexpected sendMessage response: {result}")
        try:
            self._call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})
        except TelegramApiError:
            pass
        return True

    def set_my_commands(self, commands: list[tuple[str, str]]) -> None:
        self._call(
            "setMyCommands",
            {
                "commands": json.dumps(
                    [
                        {"command": command, "description": description}
                        for command, description in commands
                    ]
                )
            },
        )

    def _extract_local_image_paths(self, message: dict[str, object]) -> tuple[str, ...]:
        photo_variants = message.get("photo")
        if isinstance(photo_variants, list) and photo_variants:
            photo = photo_variants[-1]
            if not isinstance(photo, dict):
                return ()
            file_id = photo.get("file_id")
            file_unique_id = photo.get("file_unique_id")
            if not isinstance(file_id, str):
                return ()
            image_path = self._download_to_uploads(
                file_id=file_id,
                file_name=_generate_photo_filename(str(file_unique_id or file_id)),
                file_size=_as_int(photo.get("file_size")),
            )
            return (str(image_path),)

        document = message.get("document")
        if not isinstance(document, dict) or not _is_image_document(document):
            return ()
        file_id = document.get("file_id")
        if not isinstance(file_id, str):
            return ()
        file_name = _sanitize_filename(
            str(document.get("file_name") or _generate_photo_filename(str(document.get("file_unique_id") or file_id)))
        )
        image_path = self._download_to_uploads(
            file_id=file_id,
            file_name=file_name,
            file_size=_as_int(document.get("file_size")),
        )
        return (str(image_path),)

    def _download_to_uploads(
        self,
        *,
        file_id: str,
        file_name: str,
        file_size: int | None,
    ) -> Path:
        if file_size is not None and file_size > _MAX_FILE_SIZE:
            raise TelegramApiError(
                f"Telegram file exceeds max size of {_MAX_FILE_SIZE} bytes: {file_size}"
            )

        upload_root = (Path.cwd() / _UPLOAD_DIR_NAME).resolve()
        upload_root.mkdir(parents=True, exist_ok=True)
        destination = _unique_destination(upload_root / file_name)

        file_info = self._call("getFile", {"file_id": file_id})
        if not isinstance(file_info, dict):
            raise TelegramApiError(f"Unexpected getFile response: {file_info}")
        file_path = file_info.get("file_path")
        if not isinstance(file_path, str) or not file_path:
            raise TelegramApiError(f"Unexpected getFile response: {file_info}")

        self._download_file(file_path, destination)
        if destination.stat().st_size > _MAX_FILE_SIZE:
            destination.unlink(missing_ok=True)
            raise TelegramApiError(
                f"Telegram file exceeds max size of {_MAX_FILE_SIZE} bytes after download."
            )
        return destination

    def _download_file(self, file_path: str, destination: Path) -> None:
        file_url = f"https://api.telegram.org/file/bot{self._bot_token}/{file_path}"
        try:
            with request.urlopen(file_url, timeout=30) as response:
                destination.write_bytes(response.read())
        except error.HTTPError as exc:
            body = exc.read().decode()
            raise TelegramApiError(f"Telegram HTTP error while downloading file: {body}") from exc
        except error.URLError as exc:
            raise TelegramApiError(f"Telegram file download failed: {exc}") from exc

    def _call(self, method: str, payload: dict[str, object]) -> dict[str, object] | list[object]:
        encoded = parse.urlencode(payload).encode()
        req = request.Request(f"{self._base_url}/{method}", data=encoded, method="POST")
        try:
            with request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
        except error.HTTPError as exc:
            body = exc.read().decode()
            raise TelegramApiError(f"Telegram HTTP error for {method}: {body}") from exc
        except error.URLError as exc:
            raise TelegramApiError(f"Telegram request failed for {method}: {exc}") from exc

        if not data.get("ok"):
            raise TelegramApiError(f"Telegram API error for {method}: {data}")
        return data["result"]


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]

    parts: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            parts.append(remaining)
            break
        split_at = remaining.rfind("\n", 0, limit)
        if split_at <= 0:
            split_at = limit
        parts.append(remaining[:split_at].rstrip())
        remaining = remaining[split_at:].lstrip()
    return [part for part in parts if part]


def _sanitize_filename(name: str) -> str:
    base_name = Path(name).name
    safe_name = _SAFE_FILENAME_RE.sub("_", base_name)
    if not safe_name.strip("."):
        return "unnamed"
    return safe_name


def _sanitize_caption(text: str) -> str:
    return _CONTROL_CHAR_RE.sub("", text).strip()


def _unique_destination(destination: Path) -> Path:
    if not destination.exists():
        return destination
    stem = destination.stem
    suffix = destination.suffix
    for index in range(1, 100):
        candidate = destination.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    timestamp = datetime.now(tz=timezone.utc).strftime("%H%M%S%f")
    return destination.with_name(f"{stem}_{timestamp}{suffix}")


def _generate_photo_filename(file_unique_id: str) -> str:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    return f"photo_{timestamp}_{file_unique_id[:8]}.jpg"


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    return None


def _is_image_document(document: dict[str, object]) -> bool:
    mime_type = document.get("mime_type")
    if isinstance(mime_type, str) and mime_type.startswith("image/"):
        return True
    file_name = document.get("file_name")
    if not isinstance(file_name, str):
        return False
    return Path(file_name).suffix.lower() in _IMAGE_DOCUMENT_EXTENSIONS


def is_missing_topic_error(exc: TelegramApiError) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "message thread not found",
            "message thread id is invalid",
            "topic_deleted",
            "topic closed",
            "thread not found",
        )
    )


def is_topic_edit_permission_error(exc: TelegramApiError) -> bool:
    message = str(exc).lower()
    return any(
        token in message
        for token in (
            "not enough rights",
            "chat_admin_required",
            "administrator rights",
        )
    )
