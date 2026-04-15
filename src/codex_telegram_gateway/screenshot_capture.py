from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
import sys
import time
from typing import Protocol

from codex_telegram_gateway.config import GatewayConfig


class ScreenshotCaptureError(RuntimeError):
    pass


@dataclass(frozen=True)
class ScreenshotCapture:
    file_path: Path
    send_as_document: bool = False


class ScreenshotProvider(Protocol):
    def capture_thread(
        self,
        *,
        thread_id: str,
        thread_title: str,
        project_id: str | None,
    ) -> ScreenshotCapture:
        ...


class MacOSWindowScreenshotProvider:
    def __init__(self, *, capture_dir: Path, app_name: str = "Codex") -> None:
        self._capture_dir = Path(capture_dir)
        self._capture_dir.mkdir(parents=True, exist_ok=True)
        self._app_name = app_name

    def capture_thread(
        self,
        *,
        thread_id: str,
        thread_title: str,
        project_id: str | None,
    ) -> ScreenshotCapture:
        del project_id
        x_pos, y_pos, width, height = self._front_window_rect()
        output_path = self._capture_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{_slug(thread_title or thread_id)}.png"
        try:
            subprocess.run(
                [
                    "screencapture",
                    "-x",
                    f"-R{x_pos},{y_pos},{width},{height}",
                    str(output_path),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ScreenshotCaptureError(exc.stderr.strip() or "screencapture failed") from exc
        if not output_path.is_file():
            raise ScreenshotCaptureError("Screenshot file was not created.")
        return ScreenshotCapture(
            file_path=output_path,
            send_as_document=send_as_document_for_path(output_path),
        )

    def _front_window_rect(self) -> tuple[int, int, int, int]:
        script = (
            'tell application "System Events"\n'
            f'  tell process "{self._app_name}"\n'
            "    set frontWindow to front window\n"
            "    set {xPos, yPos} to position of frontWindow\n"
            "    set {winWidth, winHeight} to size of frontWindow\n"
            "    return (xPos as text) & \",\" & (yPos as text) & \",\" & (winWidth as text) & \",\" & (winHeight as text)\n"
            "  end tell\n"
            "end tell"
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            raise ScreenshotCaptureError(exc.stderr.strip() or "Unable to read Codex window geometry.") from exc
        match = re.match(r"\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$", result.stdout)
        if match is None:
            raise ScreenshotCaptureError("Invalid Codex window geometry returned by AppleScript.")
        x_pos, y_pos, width, height = (int(value) for value in match.groups())
        if width <= 0 or height <= 0:
            raise ScreenshotCaptureError("Codex window geometry is empty.")
        return x_pos, y_pos, width, height


def build_screenshot_provider(config: GatewayConfig) -> ScreenshotProvider | None:
    if sys.platform != "darwin":
        return None
    return MacOSWindowScreenshotProvider(
        capture_dir=config.state_database_path.parent / "screenshots",
        app_name="Codex",
    )


def send_as_document_for_path(
    file_path: Path,
    *,
    photo_size_limit_bytes: int = 10_000_000,
) -> bool:
    return file_path.stat().st_size > photo_size_limit_bytes


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "codex"
