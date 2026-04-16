import json
import mimetypes
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib import error, parse, request
from uuid import uuid4

from codex_telegram_gateway.media_ingest import (
    SavedAttachment,
    attachment_prompt_text,
    unsupported_content_notice,
)


class TelegramApiError(RuntimeError):
    """Raised when the Telegram Bot API returns an error response."""


class TelegramRetryAfterError(TelegramApiError):
    """Raised when Telegram requests a retry-after cooldown."""

    def __init__(self, method: str, retry_after_seconds: int, payload: dict[str, object]) -> None:
        self.retry_after_seconds = retry_after_seconds
        super().__init__(
            f"Telegram API error for {method}: retry after {retry_after_seconds}s: {payload}"
        )


_UPLOAD_DIR_NAME = ".ccgram-uploads"
_MAX_FILE_SIZE = 50 * 1024 * 1024
_REQUEST_TIMEOUT_SECONDS = 10
_REQUEST_TIMEOUTS_BY_METHOD = {
    "answerCallbackQuery": 5,
    "answerInlineQuery": 5,
    "closeForumTopic": 5,
    "deleteForumTopic": 5,
    "deleteMessage": 5,
    "editForumTopic": 5,
    "editMessageReplyMarkup": 5,
    "editMessageText": 5,
    "sendChatAction": 5,
}
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
        payload: dict[str, object] = {"allowed_updates": json.dumps(["message", "callback_query", "inline_query"])}
        if offset is not None:
            payload["offset"] = offset
        result = self._call("getUpdates", payload)

        updates: list[dict[str, object]] = []
        for update in result:
            inline_query = update.get("inline_query")
            if isinstance(inline_query, dict):
                sender = inline_query.get("from")
                inline_query_id = inline_query.get("id")
                if not isinstance(sender, dict):
                    continue
                if not isinstance(inline_query_id, str):
                    continue
                updates.append(
                    {
                        "kind": "inline_query",
                        "update_id": int(update["update_id"]),
                        "inline_query_id": inline_query_id,
                        "from_user_id": int(sender["id"]),
                        "query": str(inline_query.get("query") or ""),
                    }
                )
                continue
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
            if not local_image_paths:
                saved_voice = self._extract_saved_voice(message)
                if saved_voice is not None:
                    if not isinstance(sender, dict):
                        continue
                    updates.append(
                        {
                            "kind": "voice_message",
                            "update_id": int(update["update_id"]),
                            "chat_id": int(chat["id"]),
                            "message_thread_id": message_thread_id,
                            "from_user_id": int(sender["id"]),
                            "file_path": saved_voice.file_path,
                        }
                    )
                    continue
            attachment_prompt = ""
            if not local_image_paths:
                saved_attachment = self._extract_saved_attachment(message)
                if saved_attachment is not None:
                    attachment_prompt = attachment_prompt_text(
                        saved_attachment,
                        user_note=_sanitize_caption(caption) if isinstance(caption, str) else "",
                    )
                else:
                    unsupported_kind = _unsupported_content_kind(message)
                    if unsupported_kind is not None:
                        if not isinstance(sender, dict):
                            continue
                        updates.append(
                            {
                                "kind": "unsupported_message",
                                "update_id": int(update["update_id"]),
                                "chat_id": int(chat["id"]),
                                "message_thread_id": message_thread_id,
                                "from_user_id": int(sender["id"]),
                                "notice": unsupported_content_notice(unsupported_kind),
                            }
                        )
                        continue
            normalized_text = text if isinstance(text, str) else ""
            if not normalized_text and isinstance(caption, str) and local_image_paths:
                normalized_text = _sanitize_caption(caption)
            if not normalized_text and attachment_prompt:
                normalized_text = attachment_prompt
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

    def send_document_file(
        self,
        chat_id: int,
        message_thread_id: int,
        file_path: str | Path,
        *,
        caption: str | None = None,
    ) -> int:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
        }
        if caption:
            payload["caption"] = caption
        result = self._call_multipart(
            "sendDocument",
            payload,
            file_field_name="document",
            file_path=Path(file_path),
        )
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise TelegramApiError(f"Unexpected sendDocument response: {result}")
        return message_id

    def send_photo_file(
        self,
        chat_id: int,
        message_thread_id: int,
        file_path: str | Path,
        *,
        caption: str | None = None,
    ) -> int:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "message_thread_id": message_thread_id,
        }
        if caption:
            payload["caption"] = caption
        result = self._call_multipart(
            "sendPhoto",
            payload,
            file_field_name="photo",
            file_path=Path(file_path),
        )
        message_id = result.get("message_id")
        if not isinstance(message_id, int):
            raise TelegramApiError(f"Unexpected sendPhoto response: {result}")
        return message_id

    def answer_callback_query(self, callback_query_id: str, text: str | None = None) -> None:
        payload: dict[str, object] = {"callback_query_id": callback_query_id}
        if text is not None:
            payload["text"] = text
        self._call("answerCallbackQuery", payload)

    def answer_inline_query(
        self,
        inline_query_id: str,
        results: list[dict[str, object]],
        *,
        cache_time: int = 0,
        is_personal: bool = True,
    ) -> None:
        self._call(
            "answerInlineQuery",
            {
                "inline_query_id": inline_query_id,
                "results": json.dumps(results),
                "cache_time": cache_time,
                "is_personal": is_personal,
            },
        )

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

    def edit_message_photo_file(
        self,
        chat_id: int,
        message_id: int,
        file_path: str | Path,
        *,
        caption: str | None = None,
        reply_markup: dict[str, object] | None = None,
    ) -> None:
        media_payload: dict[str, object] = {
            "type": "photo",
            "media": "attach://photo",
        }
        if caption is not None:
            media_payload["caption"] = caption
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "media": json.dumps(media_payload),
        }
        if reply_markup is not None:
            payload["reply_markup"] = json.dumps(reply_markup)
        self._call_multipart(
            "editMessageMedia",
            payload,
            file_field_name="photo",
            file_path=Path(file_path),
        )

    def edit_message_caption(
        self,
        chat_id: int,
        message_id: int,
        caption: str,
        reply_markup: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "chat_id": chat_id,
            "message_id": message_id,
            "caption": caption,
        }
        if reply_markup is not None:
            payload["reply_markup"] = json.dumps(reply_markup)
        self._call("editMessageCaption", payload)

    def edit_forum_topic(self, chat_id: int, message_thread_id: int, name: str) -> None:
        self._call(
            "editForumTopic",
            {
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
                "name": name[:128],
            },
        )

    def close_forum_topic(self, chat_id: int, message_thread_id: int) -> None:
        self._call(
            "closeForumTopic",
            {
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
            },
        )

    def delete_forum_topic(self, chat_id: int, message_thread_id: int) -> None:
        self._call(
            "deleteForumTopic",
            {
                "chat_id": chat_id,
                "message_thread_id": message_thread_id,
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

    def set_my_commands(
        self,
        commands: list[tuple[str, str]],
        scope: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "commands": json.dumps(
                [
                    {"command": command, "description": description}
                    for command, description in commands
                ]
            )
        }
        if scope is not None:
            payload["scope"] = json.dumps(scope)
        self._call("setMyCommands", payload)

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

    def _extract_saved_attachment(self, message: dict[str, object]) -> SavedAttachment | None:
        document = message.get("document")
        if isinstance(document, dict) and not _is_image_document(document):
            file_id = document.get("file_id")
            if not isinstance(file_id, str):
                return None
            file_name = _sanitize_filename(
                str(document.get("file_name") or _generated_attachment_name("document", document))
            )
            saved_path = self._download_to_uploads(
                file_id=file_id,
                file_name=file_name,
                file_size=_as_int(document.get("file_size")),
            )
            return SavedAttachment(
                file_path=str(saved_path),
                media_kind=_document_media_kind(document),
                original_file_name=file_name,
            )

        audio = message.get("audio")
        if isinstance(audio, dict):
            return self._download_generic_attachment(audio, prefix="audio", media_kind="audio")

        video = message.get("video")
        if isinstance(video, dict):
            return self._download_generic_attachment(video, prefix="video", media_kind="video")

        return None

    def _extract_saved_voice(self, message: dict[str, object]) -> SavedAttachment | None:
        voice = message.get("voice")
        if not isinstance(voice, dict):
            return None
        file_id = voice.get("file_id")
        if not isinstance(file_id, str):
            return None
        file_name = _sanitize_filename(_generated_voice_name(voice))
        saved_path = self._download_to_uploads(
            file_id=file_id,
            file_name=file_name,
            file_size=_as_int(voice.get("file_size")),
        )
        return SavedAttachment(
            file_path=str(saved_path),
            media_kind="voice",
            original_file_name=file_name,
        )

    def _download_generic_attachment(
        self,
        payload: dict[str, object],
        *,
        prefix: str,
        media_kind: str,
    ) -> SavedAttachment | None:
        file_id = payload.get("file_id")
        if not isinstance(file_id, str):
            return None
        file_name = _sanitize_filename(
            str(payload.get("file_name") or _generated_attachment_name(prefix, payload))
        )
        saved_path = self._download_to_uploads(
            file_id=file_id,
            file_name=file_name,
            file_size=_as_int(payload.get("file_size")),
        )
        return SavedAttachment(
            file_path=str(saved_path),
            media_kind=media_kind,
            original_file_name=file_name,
        )

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
            with request.urlopen(req, timeout=_request_timeout_seconds(method)) as response:
                data = json.loads(response.read().decode())
        except error.HTTPError as exc:
            body = exc.read().decode()
            try:
                data = json.loads(body)
            except json.JSONDecodeError:
                raise TelegramApiError(f"Telegram HTTP error for {method}: {body}") from exc
            self._raise_api_error(method, data)
        except error.URLError as exc:
            raise TelegramApiError(f"Telegram request failed for {method}: {exc}") from exc

        if not data.get("ok"):
            self._raise_api_error(method, data)
        return data["result"]

    def _call_multipart(
        self,
        method: str,
        payload: dict[str, object],
        *,
        file_field_name: str,
        file_path: Path,
    ) -> dict[str, object] | list[object]:
        boundary = f"codex-telegram-{uuid4().hex}"
        body = _encode_multipart_form_data(
            payload,
            file_field_name=file_field_name,
            file_path=file_path,
            boundary=boundary,
        )
        req = request.Request(
            f"{self._base_url}/{method}",
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with request.urlopen(req, timeout=30) as response:
                data = json.loads(response.read().decode())
        except error.HTTPError as exc:
            body_text = exc.read().decode()
            try:
                data = json.loads(body_text)
            except json.JSONDecodeError:
                raise TelegramApiError(f"Telegram HTTP error for {method}: {body_text}") from exc
            self._raise_api_error(method, data)
        except error.URLError as exc:
            raise TelegramApiError(f"Telegram request failed for {method}: {exc}") from exc

        if not data.get("ok"):
            self._raise_api_error(method, data)
        return data["result"]

    @staticmethod
    def _raise_api_error(method: str, data: dict[str, object]) -> None:
        retry_after_seconds = _retry_after_seconds(data)
        if retry_after_seconds is not None:
            raise TelegramRetryAfterError(method, retry_after_seconds, data)
        raise TelegramApiError(f"Telegram API error for {method}: {data}")


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


def _retry_after_seconds(data: dict[str, object]) -> int | None:
    parameters = data.get("parameters")
    if not isinstance(parameters, dict):
        return None
    retry_after = parameters.get("retry_after")
    if isinstance(retry_after, int):
        return max(1, retry_after)
    return None


def _request_timeout_seconds(method: str) -> int:
    return _REQUEST_TIMEOUTS_BY_METHOD.get(method, _REQUEST_TIMEOUT_SECONDS)


def _encode_multipart_form_data(
    payload: dict[str, object],
    *,
    file_field_name: str,
    file_path: Path,
    boundary: str,
) -> bytes:
    lines: list[bytes] = []
    for key, value in payload.items():
        lines.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                f"{value}\r\n".encode(),
            ]
        )
    lines.extend(
        [
            f"--{boundary}\r\n".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field_name}"; '
                f'filename="{file_path.name}"\r\n'
            ).encode(),
            b"Content-Type: application/octet-stream\r\n\r\n",
            file_path.read_bytes(),
            b"\r\n",
            f"--{boundary}--\r\n".encode(),
        ]
    )
    return b"".join(lines)


def _is_image_document(document: dict[str, object]) -> bool:
    mime_type = document.get("mime_type")
    if isinstance(mime_type, str) and mime_type.startswith("image/"):
        return True
    file_name = document.get("file_name")
    if not isinstance(file_name, str):
        return False
    return Path(file_name).suffix.lower() in _IMAGE_DOCUMENT_EXTENSIONS


def _document_media_kind(document: dict[str, object]) -> str:
    mime_type = document.get("mime_type")
    if isinstance(mime_type, str):
        if mime_type == "application/pdf":
            return "pdf"
        if mime_type.startswith("text/"):
            return "text"
    file_name = document.get("file_name")
    if isinstance(file_name, str) and Path(file_name).suffix.lower() in {".txt", ".md", ".rst", ".json", ".yaml", ".yml"}:
        return "text"
    return "document"


def _generated_attachment_name(prefix: str, payload: dict[str, object]) -> str:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    unique_id = str(payload.get("file_unique_id") or payload.get("file_id") or "file")[:8]
    mime_type = payload.get("mime_type")
    suffix = ""
    if isinstance(mime_type, str):
        guessed = mimetypes.guess_extension(mime_type)
        if isinstance(guessed, str):
            suffix = guessed
    return f"{prefix}_{timestamp}_{unique_id}{suffix}"


def _generated_voice_name(payload: dict[str, object]) -> str:
    timestamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d_%H%M%S")
    unique_id = str(payload.get("file_unique_id") or payload.get("file_id") or "voice")[:8]
    return f"voice_{timestamp}_{unique_id}.ogg"


def _unsupported_content_kind(message: dict[str, object]) -> str | None:
    if isinstance(message.get("sticker"), dict):
        return "sticker"
    if any(
        key in message
        for key in (
            "animation",
            "contact",
            "dice",
            "game",
            "location",
            "poll",
            "story",
            "venue",
            "video_note",
        )
    ):
        return "generic"
    return None


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
