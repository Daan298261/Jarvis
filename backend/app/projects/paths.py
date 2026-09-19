from __future__ import annotations

from pathlib import Path

from ..config import data_dir


def project_root(project_id: str) -> Path:
    root = data_dir() / "projects" / project_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_media_dir(project_id: str) -> Path:
    media = project_root(project_id) / "media"
    media.mkdir(parents=True, exist_ok=True)
    return media
