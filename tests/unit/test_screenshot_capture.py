from pathlib import Path
import subprocess

from codex_telegram_gateway.screenshot_capture import (
    MacOSWindowScreenshotProvider,
    send_as_document_for_path,
)


def test_send_as_document_for_path_respects_size_threshold(tmp_path) -> None:
    screenshot_path = tmp_path / "capture.png"
    screenshot_path.write_bytes(b"0123456789")

    assert send_as_document_for_path(screenshot_path, photo_size_limit_bytes=9) is True
    assert send_as_document_for_path(screenshot_path, photo_size_limit_bytes=10) is False


def test_macos_window_screenshot_provider_uses_osascript_and_screencapture(tmp_path, monkeypatch) -> None:
    calls: list[tuple[str, ...]] = []

    def fake_run(
        args: list[str],
        *,
        check: bool,
        capture_output: bool = False,
        text: bool = False,
    ) -> subprocess.CompletedProcess[str]:
        calls.append(tuple(args))
        if args[0] == "osascript":
            return subprocess.CompletedProcess(args, 0, stdout="10,20,300,400\n", stderr="")
        if args[0] == "screencapture":
            Path(args[-1]).write_bytes(b"\x89PNG\r\n\x1a\n")
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        raise AssertionError(f"Unexpected command: {args}")

    monkeypatch.setattr("codex_telegram_gateway.screenshot_capture.subprocess.run", fake_run)

    provider = MacOSWindowScreenshotProvider(
        capture_dir=tmp_path,
        app_name="Codex",
    )

    capture = provider.capture_thread(
        thread_id="thread-1",
        thread_title="Review screenshot flow",
        project_id="/Users/kangmo/sacle/src/gateway-project",
    )

    assert capture.file_path.exists()
    assert capture.file_path.suffix == ".png"
    assert capture.send_as_document is False
    assert calls[0][:2] == ("osascript", "-e")
    assert calls[1][:2] == ("screencapture", "-x")
