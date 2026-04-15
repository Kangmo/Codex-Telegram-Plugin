import json
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib import error, request
from uuid import uuid4

from codex_telegram_gateway.config import GatewayConfig


_CALLBACK_PREFIX = "gw:voice:"
_CALLBACK_SEND = f"{_CALLBACK_PREFIX}send"
_CALLBACK_DROP = f"{_CALLBACK_PREFIX}drop"

_PROVIDER_DEFAULTS = {
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "whisper-1",
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "whisper-large-v3",
    },
}


@dataclass(frozen=True)
class TranscriptionResult:
    text: str
    language: str | None = None


class TranscriptionProvider(Protocol):
    def transcribe(self, audio_path: Path | str) -> TranscriptionResult:
        ...


class OpenAICompatibleTranscriptionProvider:
    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        base_url: str,
        language: str | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._language = language

    def transcribe(self, audio_path: Path | str) -> TranscriptionResult:
        file_path = Path(audio_path)
        body, boundary = _encode_multipart_form_data(
            {
                "model": self._model,
                "language": self._language,
            },
            file_field_name="file",
            file_path=file_path,
        )
        req = request.Request(
            f"{self._base_url}/audio/transcriptions",
            data=body,
            method="POST",
        )
        req.headers["Authorization"] = f"Bearer {self._api_key}"
        req.headers["Content-Type"] = f"multipart/form-data; boundary={boundary}"
        try:
            with request.urlopen(req, timeout=60) as response:
                payload = json.loads(response.read().decode())
        except error.HTTPError as exc:
            body_text = exc.read().decode()
            raise RuntimeError(f"Voice transcription failed: {body_text}") from exc
        except error.URLError as exc:
            raise RuntimeError(f"Voice transcription request failed: {exc}") from exc
        text = str(payload.get("text") or "").strip()
        if not text:
            raise RuntimeError("Voice transcription returned no text.")
        language = payload.get("language")
        return TranscriptionResult(
            text=text,
            language=str(language) if isinstance(language, str) and language else None,
        )


def build_transcription_provider(config: GatewayConfig) -> TranscriptionProvider | None:
    provider_name = config.voice_transcription_provider.strip().lower()
    if not provider_name:
        return None
    provider_defaults = _PROVIDER_DEFAULTS.get(provider_name)
    if provider_defaults is None:
        raise ValueError(f"Unknown voice transcription provider: {provider_name}")
    api_key = config.voice_transcription_api_key.strip()
    if not api_key:
        raise ValueError("Missing voice transcription API key.")
    base_url = config.voice_transcription_base_url.strip() or provider_defaults["base_url"]
    model = config.voice_transcription_model.strip() or provider_defaults["model"]
    language = config.voice_transcription_language.strip() or None
    return OpenAICompatibleTranscriptionProvider(
        api_key=api_key,
        model=model,
        base_url=base_url,
        language=language,
    )


def render_voice_prompt(transcript_text: str) -> tuple[str, dict[str, object]]:
    return (
        f"Voice transcription\n\n{transcript_text}",
        {
            "inline_keyboard": [
                [{"text": "Send", "callback_data": _CALLBACK_SEND}],
                [{"text": "Discard", "callback_data": _CALLBACK_DROP}],
            ]
        },
    )


def parse_voice_callback(data: str) -> str | None:
    if data == _CALLBACK_SEND:
        return "send"
    if data == _CALLBACK_DROP:
        return "drop"
    return None


def _encode_multipart_form_data(
    payload: dict[str, object],
    *,
    file_field_name: str,
    file_path: Path,
) -> tuple[bytes, str]:
    boundary = f"----CodexTelegramVoice{uuid4().hex}"
    parts: list[bytes] = []
    for key, value in payload.items():
        if value in {None, ""}:
            continue
        parts.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    parts.extend(
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
    return b"".join(parts), boundary
