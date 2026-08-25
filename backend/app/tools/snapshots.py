from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir

_SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
    "models",
    "runtime",
}
_MAX_FILES = 4000
_MAX_BYTES = 200 * 1024 * 1024


def backup_root(context: dict[str, Any] | None = None) -> Path:
    custom = (context or {}).get("backup_root")
    if custom:
        path = Path(custom)
        path.mkdir(parents=True, exist_ok=True)
        return path
    path = data_dir() / "backups"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _iter_files(source: Path) -> list[Path]:
    if source.is_file():
        return [source]
    files: list[Path] = []
    for item in source.rglob("*"):
        if not item.is_file():
            continue
        if any(part in _SKIP_DIR_NAMES for part in item.parts):
            continue
        files.append(item)
        if len(files) >= _MAX_FILES:
            break
    return files


def fingerprint(source: Path) -> str:
    hasher = hashlib.sha256()
    total = 0
    files = sorted(_iter_files(source), key=lambda p: p.as_posix())
    for item in files:
        rel = item.name if source.is_file() else item.relative_to(source).as_posix()
        try:
            st = item.stat()
        except OSError:
            continue
        total += st.st_size
        hasher.update(f"{rel}:{st.st_size}:{int(st.st_mtime)}".encode("utf-8"))
        if total >= _MAX_BYTES:
            hasher.update(b":truncated")
            break
    return hasher.hexdigest()


def _manifest_path(folder: Path) -> Path:
    return folder / "manifest.json"


def list_snapshots(context: dict[str, Any] | None = None, source: Path | None = None) -> list[dict[str, Any]]:
    root = backup_root(context)
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    for folder in sorted(root.iterdir(), reverse=True):
        manifest = _manifest_path(folder)
        if not folder.is_dir() or not manifest.exists():
            continue
        try:
            payload = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if source is not None and Path(payload.get("source") or "") != source.resolve():
            continue
        payload["id"] = payload.get("id") or folder.name
        rows.append(payload)
    return rows


def create_snapshot(source: Path, context: dict[str, Any] | None = None, note: str = "") -> dict[str, Any]:
    source = source.resolve()
    if not source.exists():
        raise FileNotFoundError(f"Missing {source}")
    digest = fingerprint(source)
    existing = list_snapshots(context, source=source)
    if existing and existing[0].get("fingerprint") == digest:
        skipped = dict(existing[0])
        skipped["skipped"] = True
        skipped["reason"] = "identical to latest snapshot; no extra backup created"
        return skipped

    stamp = datetime.now(timezone.utc)
    ident = stamp.strftime("%Y%m%d%H%M%S") + "-" + uuid.uuid4().hex[:8]
    folder = backup_root(context) / ident
    tree = folder / "tree"
    tree.mkdir(parents=True, exist_ok=True)
    copied = 0
    bytes_copied = 0
    if source.is_file():
        shutil.copy2(source, tree / source.name)
        copied = 1
        bytes_copied = source.stat().st_size
    else:
        for item in _iter_files(source):
            rel = item.relative_to(source)
            dest = tree / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest)
            copied += 1
            bytes_copied += item.stat().st_size
            if bytes_copied >= _MAX_BYTES:
                break
    payload = {
        "id": ident,
        "source": str(source),
        "created_at": stamp.isoformat(),
        "fingerprint": digest,
        "files": copied,
        "bytes": bytes_copied,
        "note": note or "",
        "skipped": False,
    }
    _manifest_path(folder).write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def restore_snapshot(snapshot_id: str, destination: Path, context: dict[str, Any] | None = None) -> dict[str, Any]:
    folder = backup_root(context) / snapshot_id
    manifest = _manifest_path(folder)
    tree = folder / "tree"
    if not manifest.exists() or not tree.exists():
        raise FileNotFoundError(f"Snapshot {snapshot_id} not found")
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    destination = destination.resolve()
    if destination.suffix and not destination.exists():
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        destination.mkdir(parents=True, exist_ok=True)
    restored = 0
    entries = [p for p in tree.rglob("*") if p.is_file()] if tree.is_dir() else []
    into_dir = destination.is_dir() or not destination.suffix
    for item in entries:
        rel = item.relative_to(tree)
        dest = (destination / rel) if into_dir else destination
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, dest)
        restored += 1
    payload["restored"] = restored
    payload["destination"] = str(destination)
    return payload
