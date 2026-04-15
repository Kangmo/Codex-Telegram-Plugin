from dataclasses import dataclass
import mimetypes
from pathlib import Path


_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif"})


@dataclass(frozen=True)
class SendBrowserEntry:
    name: str
    relative_path: str
    is_dir: bool


@dataclass(frozen=True)
class SendBrowserListing:
    project_root: str
    current_relative_path: str
    entries: tuple[SendBrowserEntry, ...]
    page_index: int
    total_pages: int
    query: str | None = None


@dataclass(frozen=True)
class SendFilePreview:
    project_root: str
    relative_path: str
    file_name: str
    size_bytes: int
    mime_type: str
    send_as_photo: bool


def resolve_send_target(project_root: Path | str, relative_path: str) -> Path | None:
    root_path = Path(project_root).expanduser().resolve()
    target = (root_path / relative_path).resolve()
    try:
        target.relative_to(root_path)
    except ValueError:
        return None
    if not target.exists() or not target.is_file():
        return None
    return target


def browse_project_files(
    project_root: Path | str,
    *,
    current_relative_path: str,
    page_index: int,
    page_size: int,
) -> SendBrowserListing:
    root_path = Path(project_root).expanduser().resolve()
    current_path = root_path if current_relative_path in {"", "."} else (root_path / current_relative_path).resolve()
    try:
        current_path.relative_to(root_path)
    except ValueError as exc:
        raise ValueError("Current path must stay inside the project root.") from exc
    if not current_path.is_dir():
        raise ValueError("Current path must be a directory.")

    entries = sorted(
        [
            SendBrowserEntry(
                name=child.name,
                relative_path=_relative_path(root_path, child),
                is_dir=child.is_dir(),
            )
            for child in current_path.iterdir()
            if not child.name.startswith(".")
            and _is_safe_child(root_path, child)
            and (child.is_dir() or child.is_file())
        ],
        key=lambda entry: (not entry.is_dir, entry.name.lower(), entry.relative_path),
    )
    return _paginate_listing(
        project_root=root_path,
        current_relative_path=current_relative_path or ".",
        entries=entries,
        page_index=page_index,
        page_size=page_size,
        query=None,
    )


def search_project_files(
    project_root: Path | str,
    query: str,
    *,
    page_index: int,
    page_size: int,
) -> SendBrowserListing:
    root_path = Path(project_root).expanduser().resolve()
    normalized_query = query.strip()
    entries: list[SendBrowserEntry] = []
    exact_target = _resolve_path_within_root(root_path, normalized_query)
    if exact_target is not None and (exact_target.is_dir() or exact_target.is_file()):
        entries = [
            SendBrowserEntry(
                name=exact_target.name,
                relative_path=_relative_path(root_path, exact_target),
                is_dir=exact_target.is_dir(),
            )
        ]
    elif any(token in normalized_query for token in "*?[]"):
        entries = [
            SendBrowserEntry(
                name=match.name,
                relative_path=_relative_path(root_path, match),
                is_dir=match.is_dir(),
            )
            for match in root_path.rglob(normalized_query)
            if _is_safe_child(root_path, match) and (match.is_file() or match.is_dir())
        ]
    else:
        lowered_query = normalized_query.lower()
        entries = [
            SendBrowserEntry(
                name=match.name,
                relative_path=_relative_path(root_path, match),
                is_dir=match.is_dir(),
            )
            for match in root_path.rglob("*")
            if _is_safe_child(root_path, match)
            and match.is_file()
            and lowered_query in _relative_path(root_path, match).lower()
        ]
    entries = sorted(entries, key=lambda entry: (not entry.is_dir, entry.relative_path.lower()))
    return _paginate_listing(
        project_root=root_path,
        current_relative_path=".",
        entries=entries,
        page_index=page_index,
        page_size=page_size,
        query=normalized_query,
    )


def build_send_preview(project_root: Path | str, relative_path: str) -> SendFilePreview:
    target = resolve_send_target(project_root, relative_path)
    if target is None:
        raise ValueError("Target file must exist inside the project root.")
    mime_type, _encoding = mimetypes.guess_type(target.name)
    normalized_mime_type = mime_type or "application/octet-stream"
    return SendFilePreview(
        project_root=str(Path(project_root).expanduser().resolve()),
        relative_path=_relative_path(Path(project_root).expanduser().resolve(), target),
        file_name=target.name,
        size_bytes=target.stat().st_size,
        mime_type=normalized_mime_type,
        send_as_photo=_is_photo_like(target, normalized_mime_type),
    )


def _paginate_listing(
    *,
    project_root: Path,
    current_relative_path: str,
    entries: list[SendBrowserEntry],
    page_index: int,
    page_size: int,
    query: str | None,
) -> SendBrowserListing:
    total_pages = max(1, (len(entries) + page_size - 1) // page_size)
    safe_page_index = min(max(page_index, 0), total_pages - 1)
    start = safe_page_index * page_size
    page_entries = tuple(entries[start : start + page_size])
    return SendBrowserListing(
        project_root=str(project_root),
        current_relative_path=current_relative_path,
        entries=page_entries,
        page_index=safe_page_index,
        total_pages=total_pages,
        query=query,
    )


def _resolve_path_within_root(project_root: Path, relative_path: str) -> Path | None:
    target = (project_root / relative_path).resolve()
    try:
        target.relative_to(project_root)
    except ValueError:
        return None
    if not target.exists():
        return None
    return target


def _is_safe_child(project_root: Path, child_path: Path) -> bool:
    try:
        child_path.resolve().relative_to(project_root)
    except (ValueError, OSError):
        return False
    return True


def _relative_path(project_root: Path, target: Path) -> str:
    relative_path = target.resolve().relative_to(project_root)
    return str(relative_path).replace("\\", "/") or "."


def _is_photo_like(target: Path, mime_type: str) -> bool:
    return mime_type.startswith("image/") or target.suffix.lower() in _IMAGE_EXTENSIONS
