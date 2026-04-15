from dataclasses import dataclass


@dataclass(frozen=True)
class SavedAttachment:
    file_path: str
    media_kind: str
    original_file_name: str


def attachment_prompt_text(
    attachment: SavedAttachment,
    *,
    user_note: str = "",
) -> str:
    if attachment.media_kind == "pdf":
        prompt = (
            f"I've uploaded a PDF to {attachment.file_path}. "
            "Please inspect or read it as needed."
        )
    elif attachment.media_kind == "video":
        prompt = (
            f"I've uploaded a video file to {attachment.file_path}. "
            "Please inspect the media file as needed."
        )
    elif attachment.media_kind == "audio":
        prompt = (
            f"I've uploaded an audio file to {attachment.file_path}. "
            "Please inspect the media file as needed."
        )
    elif attachment.media_kind == "text":
        prompt = (
            f"I've uploaded a text file to {attachment.file_path}. "
            "Please inspect or read it as needed."
        )
    else:
        prompt = (
            f"I've uploaded a file to {attachment.file_path}. "
            "Please inspect or read it as needed."
        )

    if not user_note:
        return prompt
    return f"{prompt}\n\nUser note: {user_note}"


def unsupported_content_notice(content_kind: str) -> str:
    if content_kind == "sticker":
        return "⚠ Stickers are not supported yet. Use text, photos, documents, audio, or video."
    if content_kind == "voice":
        return "⚠ Voice messages are not supported yet. Use text, photos, documents, audio, or video."
    return "⚠ This media type is not supported yet. Use text, photos, documents, audio, or video."
