from __future__ import annotations

from pathlib import Path

from .. import config
from ..config import resolved_data_sidecar_dir

# RFC-0121: uploads without an explicit portal project land here (not in SQLite).
UNGROUPED_MEDIA_PROJECT_ID = "_media_ungrouped"


def projects_root() -> Path:
    """`data/projects`, or extra-drive `Jarvis/runtime/projects` when C: cannot fit."""
    dest = resolved_data_sidecar_dir(
        "projects",
        local=config.data_dir() / "projects",
        markers=(),
        need_bytes=2 * 1024**3,
    )
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def project_root(project_id: str) -> Path:
    root = projects_root() / project_id
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
    """Path relative to ``projects_root()`` parent layout (`projects/<id>/media/<upload>`)."""
    return f"projects/{project_id}/media/{upload_id}"


def resolve_projects_relative(relative_path: str) -> Path | None:
    """Resolve a stored `projects/...` relative path onto the live projects root."""
    text = str(relative_path or "").replace("\\", "/").lstrip("/")
    if not text.startswith("projects/"):
        return None
    rest = text[len("projects/") :]
    return projects_root() / rest if rest else projects_root()


def resolve_media_project_id(project_id: str | None) -> str:
    pid = (project_id or "").strip()
    return pid or UNGROUPED_MEDIA_PROJECT_ID
