"""RFC-0095 module catalog download jobs (allowlisted git URLs only)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import threading
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config import data_dir, repo_root

logger = logging.getLogger(__name__)

GITHUB_RE = re.compile(r"^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$", re.I)


@dataclass(frozen=True)
class CatalogSource:
    entry_id: str
    source_url: str
    slug: str


def library_projects_path() -> Path:
    """Jarvis-managed library root (`projects/` beside the repo)."""
    return repo_root() / "projects"


def _library_projects_root() -> Path:
    return library_projects_path()


def desktop_projects_root() -> Path:
    return Path.home() / "Desktop" / "projects"


def le_gated_roots() -> list[Path]:
    roots: list[Path] = []
    win = Path(r"C:\Users\daanv\projects\jarvis-ig\le-gated")
    roots.append(win)
    roots.append(repo_root() / "projects" / "le-gated")
    roots.append(_library_projects_root() / "le-gated")
    return roots


def catalog_library_root() -> Path:
    path = _library_projects_root()
    path.mkdir(parents=True, exist_ok=True)
    return path


def slug_from_url(url: str) -> str:
    match = GITHUB_RE.match((url or "").strip())
    if match:
        return match.group(2)
    parsed = urlparse(url)
    tail = (parsed.path or "").rstrip("/").split("/")[-1]
    return tail or "module"


def parse_github_url(url: str) -> tuple[str, str] | None:
    match = GITHUB_RE.match((url or "").strip())
    if not match:
        return None
    return match.group(1), match.group(2)


@dataclass
class DownloadJob:
    job_id: str
    entry_id: str
    status: str = "queued"  # queued|running|ready|error
    detail: str = ""
    error: str = ""
    local_path: str = ""
    mode: str = "clone"
    dest: str = "library"


_LOCK = threading.Lock()
_JOBS: dict[str, DownloadJob] = {}
_ALLOWLIST: dict[str, CatalogSource] = {}


def register_allowlisted_source(entry_id: str, source_url: str, *, slug: str = "") -> None:
    key = (entry_id or "").strip()
    url = (source_url or "").strip()
    if not key or not url:
        return
    resolved_slug = slug or slug_from_url(url)
    _ALLOWLIST[key] = CatalogSource(entry_id=key, source_url=url, slug=resolved_slug)
    _ALLOWLIST[resolved_slug] = CatalogSource(entry_id=key, source_url=url, slug=resolved_slug)


def allowlisted_source(entry_id: str) -> CatalogSource | None:
    key = (entry_id or "").strip()
    if key in _ALLOWLIST:
        return _ALLOWLIST[key]
    for item in _ALLOWLIST.values():
        if item.slug == key:
            return item
    return None


def reset_download_jobs() -> None:
    with _LOCK:
        _JOBS.clear()


def get_job(job_id: str) -> DownloadJob | None:
    with _LOCK:
        return _JOBS.get(job_id)


def job_snapshot(job_id: str) -> dict[str, Any] | None:
    job = get_job(job_id)
    return asdict(job) if job else None


def _set_job(job_id: str, **kwargs: Any) -> DownloadJob:
    with _LOCK:
        job = _JOBS.get(job_id) or DownloadJob(job_id=job_id, entry_id=str(kwargs.get("entry_id") or ""))
        for key, value in kwargs.items():
            setattr(job, key, value)
        _JOBS[job_id] = job
        return job


def _dest_root(dest: str) -> Path:
    if dest == "desktop_projects":
        root = desktop_projects_root()
    else:
        root = catalog_library_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_dest_dir(root: Path, slug: str) -> Path:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", slug).strip("-") or "module"
    dest = (root / cleaned).resolve()
    if not str(dest).startswith(str(root.resolve())):
        raise ValueError("destination escapes sandbox")
    return dest


def _run_git_clone(url: str, dest: Path) -> None:
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(dest)],
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "git clone failed")[:800])


def _run_zip_download(url: str, dest: Path) -> None:
    parsed = parse_github_url(url)
    if not parsed:
        raise ValueError("zip download requires a GitHub source_url")
    owner, repo = parsed
    archive_url = f"https://github.com/{owner}/{repo}/archive/refs/heads/main.zip"
    import urllib.request

    dest.parent.mkdir(parents=True, exist_ok=True)
    zip_path = dest.parent / f"{repo}-download.zip"
    try:
        urllib.request.urlretrieve(archive_url, zip_path)
        extract_root = dest.parent / f"{repo}-extract"
        if extract_root.exists():
            shutil.rmtree(extract_root)
        extract_root.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            for member in zf.namelist():
                member_path = (extract_root / member).resolve()
                if not str(member_path).startswith(str(extract_root.resolve())):
                    raise ValueError("zip path escapes destination")
            zf.extractall(extract_root)
        top_dirs = [p for p in extract_root.iterdir() if p.is_dir()]
        if dest.exists():
            shutil.rmtree(dest)
        if len(top_dirs) == 1:
            shutil.move(str(top_dirs[0]), str(dest))
        else:
            shutil.move(str(extract_root), str(dest))
    finally:
        if zip_path.exists():
            zip_path.unlink(missing_ok=True)


def _persist_download_record(entry_id: str, local_path: Path, source_url: str) -> None:
    cache = data_dir() / "module-cache" / "downloads.json"
    cache.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {}
    if cache.is_file():
        try:
            payload = json.loads(cache.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            payload = {}
    payload[entry_id] = {
        "local_path": str(local_path),
        "source_url": source_url,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
    }
    cache.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def recorded_local_path(entry_id: str) -> str | None:
    cache = data_dir() / "module-cache" / "downloads.json"
    if not cache.is_file():
        return None
    try:
        payload = json.loads(cache.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    row = payload.get(entry_id) if isinstance(payload, dict) else None
    if not isinstance(row, dict):
        return None
    path = str(row.get("local_path") or "")
    if path and Path(path).is_dir():
        return path
    return None


async def start_download(entry_id: str, *, mode: str = "clone", dest: str = "library") -> DownloadJob:
    source = allowlisted_source(entry_id)
    if source is None:
        raise ValueError("catalog entry is not allowlisted for download")
    job_id = uuid.uuid4().hex
    job = _set_job(
        job_id,
        entry_id=source.entry_id,
        status="running",
        detail="download started",
        mode=mode,
        dest=dest,
    )

    async def _runner() -> None:
        try:
            root = _dest_root(dest)
            target = _safe_dest_dir(root, source.slug)
            if mode == "zip":
                await asyncio.to_thread(_run_zip_download, source.source_url, target)
            else:
                await asyncio.to_thread(_run_git_clone, source.source_url, target)
            _persist_download_record(source.entry_id, target, source.source_url)
            _set_job(
                job_id,
                status="ready",
                detail="download complete",
                local_path=str(target),
                error="",
            )
        except Exception as exc:
            logger.exception("module download failed")
            _set_job(job_id, status="error", error=str(exc)[:800], detail="download failed")

    asyncio.create_task(_runner())
    return job
