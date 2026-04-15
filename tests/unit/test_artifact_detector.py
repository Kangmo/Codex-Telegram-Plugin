from codex_telegram_gateway.models import CodexEvent


def test_build_artifact_events_detects_project_root_photo_and_document(tmp_path, monkeypatch) -> None:
    monkeypatch.chdir(tmp_path)
    project_root = tmp_path / "project"
    photo_path = project_root / "artifacts" / "diagram.png"
    document_path = project_root / "reports" / "summary.txt"
    photo_path.parent.mkdir(parents=True)
    document_path.parent.mkdir(parents=True)
    photo_path.write_bytes(b"png-bytes")
    document_path.write_text("done\n")

    events = __import__(
        "codex_telegram_gateway.artifact_detector",
        fromlist=["build_artifact_events"],
    ).build_artifact_events(
        "thread-1",
        str(project_root),
        CodexEvent(
            event_id="thread-1:turn-1:item-2",
            thread_id="thread-1",
            kind="assistant_message",
            text="I created `artifacts/diagram.png` and wrote `reports/summary.txt` for review.",
        ),
    )

    assert [event.kind for event in events] == ["artifact_photo", "artifact_document"]
    assert [event.text for event in events] == [
        "Artifact: artifacts/diagram.png",
        "Artifact: reports/summary.txt",
    ]
    assert [event.file_path for event in events] == [str(photo_path), str(document_path)]
    assert all(event.event_id.startswith("thread-1:turn-1:item-2:artifact:") for event in events)


def test_build_artifact_events_allows_gateway_uploads_and_ignores_unsafe_or_non_signal_paths(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    upload_path = tmp_path / ".ccgram-uploads" / "reply.png"
    upload_path.parent.mkdir(parents=True)
    upload_path.write_bytes(b"png-bytes")
    outside_path = tmp_path.parent / "outside.txt"
    outside_path.write_text("secret\n")

    build_artifact_events = __import__(
        "codex_telegram_gateway.artifact_detector",
        fromlist=["build_artifact_events"],
    ).build_artifact_events

    upload_events = build_artifact_events(
        "thread-1",
        str(tmp_path / "project"),
        CodexEvent(
            event_id="thread-1:turn-1:item-3",
            thread_id="thread-1",
            kind="assistant_message",
            text="Saved `.ccgram-uploads/reply.png` from the latest run.",
        ),
    )
    ignored_events = build_artifact_events(
        "thread-1",
        str(tmp_path / "project"),
        CodexEvent(
            event_id="thread-1:turn-1:item-4",
            thread_id="thread-1",
            kind="assistant_message",
            text=(
                "The stack trace mentioned "
                f"`{outside_path}` and I also checked `tests/unit/test_daemon.py`."
            ),
        ),
    )

    assert len(upload_events) == 1
    assert upload_events[0].kind == "artifact_photo"
    assert upload_events[0].file_path == str(upload_path)
    assert ignored_events == ()
