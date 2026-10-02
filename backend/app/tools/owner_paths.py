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
