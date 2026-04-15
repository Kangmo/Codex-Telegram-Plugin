from dataclasses import dataclass
import hashlib
import mimetypes
from pathlib import Path
import re

from codex_telegram_gateway.models import CodexEvent


_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif"})
_SIGNAL_TOKENS = (
    "saved",
    "wrote",
    "written",
    "created",
    "generated",
    "exported",
    "attached",
    "uploaded",
    "artifact",
    "artifacts",
    "screenshot",
)
_BACKTICK_PATH_RE = re.compile(r"`([^`\n]+)`")
_ABSOLUTE_PATH_RE = re.compile(r"(/[^`\s]+)")
_RELATIVE_PATH_RE = re.compile(r"(?<![\w/])(?:\.ccgram-uploads|[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)+)")


@dataclass(frozen=True)
class ArtifactCandidate:
    absolute_path: str
    display_path: str
    send_as_photo: bool


def build_artifact_events(
    thread_id: str,
    project_root: str,
    source_event: CodexEvent,
) -> tuple[CodexEvent, ...]:
    if source_event.kind not in {"assistant_message", "tool_batch", "completion_summary"}:
        return ()
    candidates = detect_artifacts(project_root, source_event.text)
    return tuple(
        CodexEvent(
            event_id=_artifact_event_id(source_event.event_id, candidate.display_path),
            thread_id=thread_id,
            kind="artifact_photo" if candidate.send_as_photo else "artifact_document",
            text=f"Artifact: {candidate.display_path}",
            file_path=candidate.absolute_path,
        )
        for candidate in candidates
    )


def detect_artifacts(project_root: str, text: str) -> tuple[ArtifactCandidate, ...]:
    normalized_project_root = Path(project_root).expanduser().resolve()
    upload_root = Path(".ccgram-uploads").expanduser().resolve()
    allowed_roots = (normalized_project_root, upload_root)
    seen_paths: set[str] = set()
    candidates: list[ArtifactCandidate] = []
    for line in text.splitlines():
        if not _line_may_describe_artifact(line):
            continue
        for token in _extract_path_tokens(line):
            resolved_path = _resolve_artifact_path(token, normalized_project_root, allowed_roots)
            if resolved_path is None:
                continue
            resolved_key = str(resolved_path)
            if resolved_key in seen_paths:
                continue
            seen_paths.add(resolved_key)
            candidates.append(
                ArtifactCandidate(
                    absolute_path=resolved_key,
                    display_path=_display_path(resolved_path, normalized_project_root, upload_root),
                    send_as_photo=_is_photo_like(resolved_path),
                )
            )
    return tuple(candidates)


def _line_may_describe_artifact(line: str) -> bool:
    lowered = line.lower()
    return any(token in lowered for token in _SIGNAL_TOKENS)


def _extract_path_tokens(line: str) -> tuple[str, ...]:
    matches: list[tuple[int, str]] = []
    for pattern in (_BACKTICK_PATH_RE, _ABSOLUTE_PATH_RE, _RELATIVE_PATH_RE):
        for match in pattern.finditer(line):
            if pattern is _BACKTICK_PATH_RE:
                token = _clean_path_token(match.group(1))
            else:
                token = _clean_path_token(match.group(0))
            if token:
                matches.append((match.start(), token))
    ordered: list[str] = []
    seen: set[str] = set()
    for _index, token in sorted(matches, key=lambda item: item[0]):
        if token in seen:
            continue
        seen.add(token)
        ordered.append(token)
    return tuple(ordered)


def _clean_path_token(token: str) -> str:
    normalized = token.strip()
    while normalized and normalized[0] in "([{<\"'":
        normalized = normalized[1:]
    while normalized and normalized[-1] in ")]}>\"'.,:;!?":
        normalized = normalized[:-1]
    return normalized


def _resolve_artifact_path(
    token: str,
    project_root: Path,
    allowed_roots: tuple[Path, ...],
) -> Path | None:
    path = Path(token).expanduser()
    candidate_paths: list[Path] = []
    if path.is_absolute():
        candidate_paths.append(path)
    else:
        candidate_paths.append(project_root / path)
        if token.startswith(".ccgram-uploads/"):
            candidate_paths.append(Path(token))
    for candidate in candidate_paths:
        resolved = candidate.resolve()
        if not resolved.is_file():
            continue
        if any(_is_within_root(resolved, root) for root in allowed_roots):
            return resolved
    return None


def _display_path(target: Path, project_root: Path, upload_root: Path) -> str:
    if _is_within_root(target, project_root):
        return str(target.relative_to(project_root)).replace("\\", "/")
    if _is_within_root(target, upload_root):
        relative_path = str(target.relative_to(upload_root)).replace("\\", "/")
        return f".ccgram-uploads/{relative_path}"
    return target.name


def _is_within_root(target: Path, root: Path) -> bool:
    try:
        target.relative_to(root)
        return True
    except ValueError:
        return False


def _is_photo_like(path: Path) -> bool:
    mime_type, _encoding = mimetypes.guess_type(path.name)
    return (mime_type or "").startswith("image/") or path.suffix.lower() in _IMAGE_EXTENSIONS


def _artifact_event_id(source_event_id: str, display_path: str) -> str:
    digest = hashlib.sha1(display_path.encode("utf-8")).hexdigest()[:10]
    return f"{source_event_id}:artifact:{digest}"
