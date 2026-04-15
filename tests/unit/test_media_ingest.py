from codex_telegram_gateway.media_ingest import (
    SavedAttachment,
    attachment_prompt_text,
    unsupported_content_notice,
)


def test_attachment_prompt_text_for_pdf_includes_path_and_user_note() -> None:
    attachment = SavedAttachment(
        file_path="/tmp/project/.ccgram-uploads/spec.pdf",
        media_kind="pdf",
        original_file_name="spec.pdf",
    )

    assert attachment_prompt_text(attachment, user_note="Please summarize page 2.") == (
        "I've uploaded a PDF to /tmp/project/.ccgram-uploads/spec.pdf. "
        "Please inspect or read it as needed.\n\n"
        "User note: Please summarize page 2."
    )


def test_attachment_prompt_text_for_video_uses_media_specific_wording() -> None:
    attachment = SavedAttachment(
        file_path="/tmp/project/.ccgram-uploads/demo.mp4",
        media_kind="video",
        original_file_name="demo.mp4",
    )

    assert attachment_prompt_text(attachment) == (
        "I've uploaded a video file to /tmp/project/.ccgram-uploads/demo.mp4. "
        "Please inspect the media file as needed."
    )


def test_attachment_prompt_text_for_audio_and_text_and_generic_files() -> None:
    audio = SavedAttachment(
        file_path="/tmp/project/.ccgram-uploads/briefing.m4a",
        media_kind="audio",
        original_file_name="briefing.m4a",
    )
    text_file = SavedAttachment(
        file_path="/tmp/project/.ccgram-uploads/notes.md",
        media_kind="text",
        original_file_name="notes.md",
    )
    generic = SavedAttachment(
        file_path="/tmp/project/.ccgram-uploads/archive.bin",
        media_kind="document",
        original_file_name="archive.bin",
    )

    assert attachment_prompt_text(audio) == (
        "I've uploaded an audio file to /tmp/project/.ccgram-uploads/briefing.m4a. "
        "Please inspect the media file as needed."
    )
    assert attachment_prompt_text(text_file) == (
        "I've uploaded a text file to /tmp/project/.ccgram-uploads/notes.md. "
        "Please inspect or read it as needed."
    )
    assert attachment_prompt_text(generic) == (
        "I've uploaded a file to /tmp/project/.ccgram-uploads/archive.bin. "
        "Please inspect or read it as needed."
    )


def test_unsupported_content_notice_mentions_supported_media() -> None:
    assert unsupported_content_notice("sticker") == (
        "⚠ Stickers are not supported yet. Use text, photos, documents, audio, or video."
    )
    assert unsupported_content_notice("voice") == (
        "⚠ Voice messages are not supported yet. Use text, photos, documents, audio, or video."
    )
    assert unsupported_content_notice("animation") == (
        "⚠ This media type is not supported yet. Use text, photos, documents, audio, or video."
    )
