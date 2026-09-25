from __future__ import annotations

from pathlib import Path

from .. import config

# RFC-0121: uploads without an explicit portal project land here (not in SQLite).
UNGROUPED_MEDIA_PROJECT_ID = "_media_ungrouped"


def project_root(project_id: str) -> Path:
    root = config.data_dir() / "projects" / project_id
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_media_dir(project_id: str) -> Path:
    media = project_root(project_id) / "media"
    media.mkdir(parents=True, exist_ok=True)
    return media


def project_artifacts_dir(project_id: str) -> Path:
    artifacts = project_root(project_id) / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    return artifacts


def media_relative_path(project_id: str, upload_id: str) -> str:
    """Path relative to ``data_dir()`` for RFC-0121 colocated media."""
    return f"projects/{project_id}/media/{upload_id}"


def resolve_media_project_id(project_id: str | None) -> str:
    pid = (project_id or "").strip()
    return pid or UNGROUPED_MEDIA_PROJECT_ID
