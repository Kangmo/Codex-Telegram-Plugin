from codex_telegram_gateway.send_security import (
    build_send_preview,
    browse_project_files,
    resolve_send_target,
    search_project_files,
)


def test_browse_project_files_lists_directories_before_files_and_paginates(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    (project_root / "docs").mkdir(parents=True)
    (project_root / "images").mkdir()
    (project_root / "notes.txt").write_text("notes")
    (project_root / "report.md").write_text("report")

    listing = browse_project_files(project_root, current_relative_path=".", page_index=0, page_size=3)

    assert listing.current_relative_path == "."
    assert listing.total_pages == 2
    assert [entry.name for entry in listing.entries] == ["docs", "images", "notes.txt"]
    assert [entry.is_dir for entry in listing.entries] == [True, True, False]


def test_resolve_send_target_blocks_path_traversal_and_symlinks_outside_root(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    (tmp_path / "secret.txt").write_text("secret")
    (project_root / "notes.txt").write_text("notes")
    (project_root / "leak").symlink_to(tmp_path / "secret.txt")

    assert resolve_send_target(project_root, "notes.txt") == (project_root / "notes.txt").resolve()
    assert resolve_send_target(project_root, "../secret.txt") is None
    assert resolve_send_target(project_root, "leak") is None


def test_search_project_files_supports_exact_path_glob_and_substring(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    (project_root / "docs").mkdir(parents=True)
    (project_root / "docs" / "notes.txt").write_text("notes")
    (project_root / "docs" / "todo.md").write_text("todo")
    (project_root / "diagram.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    exact_listing = search_project_files(project_root, "docs/notes.txt", page_index=0, page_size=6)
    glob_listing = search_project_files(project_root, "*.md", page_index=0, page_size=6)
    substring_listing = search_project_files(project_root, "note", page_index=0, page_size=6)

    assert [entry.relative_path for entry in exact_listing.entries] == ["docs/notes.txt"]
    assert [entry.relative_path for entry in glob_listing.entries] == ["docs/todo.md"]
    assert [entry.relative_path for entry in substring_listing.entries] == ["docs/notes.txt"]


def test_build_send_preview_marks_images_for_photo_sending(tmp_path) -> None:
    project_root = tmp_path / "gateway-project"
    project_root.mkdir()
    image_path = project_root / "images" / "diagram.png"
    image_path.parent.mkdir()
    image_path.write_bytes(b"\x89PNG\r\n\x1a\n")

    preview = build_send_preview(project_root, "images/diagram.png")

    assert preview.relative_path == "images/diagram.png"
    assert preview.file_name == "diagram.png"
    assert preview.size_bytes == image_path.stat().st_size
    assert preview.mime_type == "image/png"
    assert preview.send_as_photo is True
