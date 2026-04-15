import io
from pathlib import Path

import pytest

from codex_telegram_gateway.config import GatewayConfig


def make_config(**overrides) -> GatewayConfig:
    return GatewayConfig(
        telegram_bot_token="test-token",
        telegram_allowed_user_ids={111},
        telegram_default_chat_id=-100100,
        sync_mode="assistant_plus_alerts",
        **overrides,
    )


def test_render_voice_prompt_and_parse_callbacks() -> None:
    voice_ingest = __import__("codex_telegram_gateway.voice_ingest", fromlist=["render_voice_prompt", "parse_voice_callback"])

    text, reply_markup = voice_ingest.render_voice_prompt("Please continue with the refactor.")

    assert text == "Voice transcription\n\nPlease continue with the refactor."
    assert reply_markup == {
        "inline_keyboard": [
            [{"text": "Send", "callback_data": "gw:voice:send"}],
            [{"text": "Discard", "callback_data": "gw:voice:drop"}],
        ]
    }
    assert voice_ingest.parse_voice_callback("gw:voice:send") == "send"
    assert voice_ingest.parse_voice_callback("gw:voice:drop") == "drop"
    assert voice_ingest.parse_voice_callback("gw:voice:other") is None


def test_build_transcription_provider_supports_defaults_and_unknown_provider() -> None:
    voice_ingest = __import__("codex_telegram_gateway.voice_ingest", fromlist=["build_transcription_provider"])

    assert voice_ingest.build_transcription_provider(make_config()) is None

    openai_provider = voice_ingest.build_transcription_provider(
        make_config(
            voice_transcription_provider="openai",
            voice_transcription_api_key="openai-key",
        )
    )
    groq_provider = voice_ingest.build_transcription_provider(
        make_config(
            voice_transcription_provider="groq",
            voice_transcription_api_key="groq-key",
        )
    )

    assert openai_provider is not None
    assert groq_provider is not None
    assert openai_provider._model == "whisper-1"
    assert groq_provider._model == "whisper-large-v3"

    with pytest.raises(ValueError, match="Unknown voice transcription provider"):
        voice_ingest.build_transcription_provider(
            make_config(
                voice_transcription_provider="unknown",
                voice_transcription_api_key="key",
            )
        )


def test_openai_compatible_transcription_provider_posts_multipart_and_parses_text(tmp_path, monkeypatch) -> None:
    voice_ingest = __import__(
        "codex_telegram_gateway.voice_ingest",
        fromlist=["OpenAICompatibleTranscriptionProvider", "TranscriptionResult"],
    )
    audio_path = tmp_path / "voice.ogg"
    audio_path.write_bytes(b"ogg-bytes")
    captured: dict[str, object] = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            del exc_type, exc, tb

        def read(self) -> bytes:
            return b'{"text":"transcribed text","language":"en"}'

    def fake_urlopen(req, timeout: int):
        captured["url"] = req.full_url
        captured["content_type"] = req.headers["Content-Type"]
        captured["body"] = req.data
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("codex_telegram_gateway.voice_ingest.request.urlopen", fake_urlopen)
    provider = voice_ingest.OpenAICompatibleTranscriptionProvider(
        api_key="test-key",
        model="whisper-1",
        base_url="https://api.openai.com/v1",
        language="en",
    )

    result = provider.transcribe(audio_path)

    assert result == voice_ingest.TranscriptionResult(text="transcribed text", language="en")
    assert captured["url"] == "https://api.openai.com/v1/audio/transcriptions"
    assert "multipart/form-data" in str(captured["content_type"])
    assert b'name="model"' in captured["body"]
    assert b'whisper-1' in captured["body"]
    assert b'name="language"' in captured["body"]
    assert b'en' in captured["body"]
    assert b'filename="voice.ogg"' in captured["body"]
