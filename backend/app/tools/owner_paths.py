"""Owner Downloads/Pictures/Desktop paths inside the allowed workspace."""

from __future__ import annotations

from pathlib import Path

from ..config import data_dir
from .safety import resolve_allowed_path


def owner_media_dir(*names: str) -> Path:
    """Owner Downloads/Pictures/Desktop when present; otherwise a Jarvis data folder."""
    for name in names:
        candidate = Path.home() / name
        try:
            if candidate.is_dir():
                return candidate
        except OSError:
            continue
    fallback = data_dir() / (names[0].lower() if names else "downloads")
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def owner_downloads_dir() -> Path:
    """Chromium / Browser Use download directory: the owner's Downloads folder."""
    dest = owner_media_dir("Downloads")
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def chromium_download_launch_kwargs() -> dict[str, str | bool]:
    """Playwright persistent-context kwargs so click-saves land in Downloads."""
    return {"accept_downloads": True, "downloads_path": str(owner_downloads_dir())}


def resolve_owner_file_path(
    raw: str | None,
    *,
    suggested_name: str,
    allowed: list[str],
    fallback_dirs: tuple[str, ...] = ("Downloads",),
) -> Path:
    """Save/open path under the allowed workspace. Default is the owner's Downloads folder."""
    name = Path(str(suggested_name or "download").strip() or "download").name
    if raw and str(raw).strip():
        target = Path(str(raw).strip()).expanduser()
        try:
            is_dir = target.is_dir()
        except OSError:
            is_dir = False
        if is_dir or str(raw).endswith(("/", "\\")):
            target = target / name
        return resolve_allowed_path(str(target), allowed)
    dest = owner_media_dir(*fallback_dirs) / name
    try:
        return resolve_allowed_path(str(dest), allowed)
    except PermissionError:
        alt = data_dir() / (fallback_dirs[0].lower() if fallback_dirs else "downloads") / name
        alt.parent.mkdir(parents=True, exist_ok=True)
        if not allowed:
            return alt
        return resolve_allowed_path(str(alt), allowed)


def resolve_workspace_dir(raw: str | None, allowed: list[str]) -> str | None:
    """Expand ~ and, when the workspace is bound, keep the path on an allowed drive."""
    text = str(raw or "").strip()
    if not text:
        return None
    expanded = str(Path(text).expanduser())
    if not allowed:
        return expanded
    return str(resolve_allowed_path(expanded, allowed))


def default_workspace_dir(allowed: list[str], *, media_only: bool = False) -> Path:
    """Documents (then Desktop/Downloads) when that folder is in the workspace."""
    for name in ("Documents", "Desktop", "Downloads"):
        candidate = Path.home() / name
        try:
            if not candidate.is_dir():
                continue
        except OSError:
            continue
        try:
            return resolve_allowed_path(str(candidate), allowed)
        except PermissionError:
            continue
    if media_only:
        raise PermissionError("Documents is not in the allowed workspace")
    if allowed:
        return resolve_allowed_path(allowed[0], allowed)
    return Path.cwd()


def resolve_project_dir(raw: str | None, allowed: list[str]) -> Path:
    """Explicit extra-drive/USB folder, or Documents when path is omitted."""
    text = str(raw or "").strip()
    if text:
        resolved = resolve_workspace_dir(text, allowed)
        return Path(resolved) if resolved else resolve_allowed_path(text, allowed)
    return default_workspace_dir(allowed)


def workspace_cwd(raw: str | None, allowed: list[str]) -> str | None:
    """Working directory for python/terminal. Omit path → Documents when the workspace is bound."""
    text = str(raw or "").strip()
    if text:
        return resolve_workspace_dir(text, allowed)
    if not allowed:
        return None
    return str(default_workspace_dir(allowed))
