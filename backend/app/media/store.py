from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from fastapi import HTTPException

from ..config import data_dir
from ..mobile.store import database, delete, get, put

MediaKind = Literal["image", "video", "audio", "file"]

DEFAULT_IMAGE_FILE_CAP = 64 * 1024 * 1024
DEFAULT_VIDEO_CAP = 512 * 1024 * 1024
DEFAULT_AUDIO_CAP = 128 * 1024 * 1024
CHUNK_RECORD_KIND = "media_chunk"
UPLOAD_RECORD_KIND = "media_upload"
LEGACY_ATTACHMENT_KIND = "attachment"
ANALYZE_ARTIFACT_KIND = "media_analyze_artifact"

_IMAGE_TYPES = {
    "image/jpeg",
    "image/jpg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
    "image/gif",
    "image/bmp",
}
_VIDEO_TYPES = {"video/mp4", "video/webm", "video/quicktime", "video/x-matroska", "video/mpeg"}
_AUDIO_TYPES = {"audio/wav", "audio/x-wav", "audio/mpeg", "audio/mp3", "audio/mp4", "audio/m4a", "audio/webm", "audio/ogg"}


def media_root() -> Path:
    path = data_dir() / "media" / "uploads"
    path.mkdir(parents=True, exist_ok=True)
    return path


def chunks_root() -> Path:
    path = data_dir() / "media" / "chunks"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def caps_for_kind(kind: MediaKind) -> int:
    if kind == "video":
        return _env_int("JARVIS_MEDIA_VIDEO_MAX_BYTES", DEFAULT_VIDEO_CAP)
    if kind == "audio":
        return _env_int("JARVIS_MEDIA_AUDIO_MAX_BYTES", DEFAULT_AUDIO_CAP)
    return _env_int("JARVIS_MEDIA_FILE_MAX_BYTES", DEFAULT_IMAGE_FILE_CAP)


def detect_kind(content_type: str, filename: str) -> MediaKind:
    ct = (content_type or "").split(";")[0].strip().lower()
    name = (filename or "").lower()
    if ct in _IMAGE_TYPES or re.search(r"\.(jpe?g|png|webp|heic|heif|gif|bmp)$", name):
        return "image"
    if ct in _VIDEO_TYPES or re.search(r"\.(mp4|webm|mov|mkv|mpeg)$", name):
        return "video"
    if ct in _AUDIO_TYPES or re.search(r"\.(wav|mp3|m4a|ogg|flac|aac)$", name):
        return "audio"
    return "file"


def _safe_name(filename: str) -> str:
    cleaned = re.sub(r"[^\w.\- ()]", "_", (filename or "upload")[:200]).strip("._")
    return cleaned or "upload"


@dataclass
class MediaUpload:
    id: str
    kind: MediaKind
    name: str
    content_type: str
    size: int
    sha256: str
    owner: str
    device_id: str | None
    created_at: float
    analyze: dict | None
    studio: dict | None

    def to_public(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "content_type": self.content_type,
            "size": self.size,
            "sha256": self.sha256,
            "owner": self.owner,
            "device_id": self.device_id,
            "created_at": self.created_at,
            "analyze": self.analyze,
            "studio": self.studio,
        }


def _record_to_upload(record: dict) -> MediaUpload:
    return MediaUpload(
        id=record["id"],
        kind=record.get("kind") or detect_kind(record.get("content_type", ""), record.get("name", "")),
        name=record.get("name") or "upload",
        content_type=record.get("content_type") or "application/octet-stream",
        size=int(record.get("size") or 0),
        sha256=record.get("sha256") or "",
        owner=record.get("owner") or record.get("device_id") or "desktop",
        device_id=record.get("device_id"),
        created_at=float(record.get("created_at") or 0),
        analyze=record.get("analyze"),
        studio=record.get("studio"),
    )


def blob_path(upload_id: str) -> Path:
    return media_root() / upload_id


def _load_record(upload_id: str) -> dict | None:
    with database() as db:
        record = get(db, UPLOAD_RECORD_KIND, upload_id)
        if record:
            return record
        legacy = get(db, LEGACY_ATTACHMENT_KIND, upload_id)
        if legacy:
            legacy = dict(legacy)
            legacy.setdefault("id", upload_id)
            legacy.setdefault("owner", legacy.get("device_id"))
            legacy.setdefault("kind", detect_kind(legacy.get("content_type", ""), legacy.get("name", "")))
            return legacy
    return None


def get_upload(upload_id: str) -> MediaUpload | None:
    record = _load_record(upload_id)
    return _record_to_upload(record) if record else None


def require_upload(upload_id: str) -> MediaUpload:
    item = get_upload(upload_id)
    if not item:
        raise HTTPException(404, "Upload not found")
    return item


def assert_access(upload: MediaUpload, *, owner_key: bool, device_id: str | None) -> None:
    if owner_key:
        return
    if device_id and upload.device_id == device_id:
        return
    if upload.owner == "desktop" and device_id:
        return
    raise HTTPException(404, "Upload not found")


def save_upload(
    data: bytes,
    *,
    kind: MediaKind | None,
    filename: str,
    content_type: str,
    owner: str,
    device_id: str | None = None,
    upload_id: str | None = None,
) -> MediaUpload:
    if not data:
        raise HTTPException(400, "Upload is empty")
    resolved_kind = kind or detect_kind(content_type, filename)
    cap = caps_for_kind(resolved_kind)
    if len(data) > cap:
        raise HTTPException(413, f"Upload exceeds {resolved_kind} limit ({cap} bytes)")
    upload_id = upload_id or str(uuid.uuid4())
    digest = hashlib.sha256(data).hexdigest()
    path = blob_path(upload_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(data)
    record = {
        "id": upload_id,
        "kind": resolved_kind,
        "name": _safe_name(filename),
        "content_type": (content_type or "application/octet-stream")[:100],
        "size": len(data),
        "sha256": digest,
        "owner": owner,
        "device_id": device_id,
        "created_at": time.time(),
        "analyze": None,
        "studio": None,
    }
    with database() as db:
        put(db, UPLOAD_RECORD_KIND, upload_id, record)
    return _record_to_upload(record)


def update_upload_record(upload_id: str, **fields) -> MediaUpload:
    with database() as db:
        record = get(db, UPLOAD_RECORD_KIND, upload_id)
        if not record:
            raise HTTPException(404, "Upload not found")
        record.update(fields)
        put(db, UPLOAD_RECORD_KIND, upload_id, record)
    return _record_to_upload(record)


def ingest_chunk(
    upload_id: str,
    chunk_index: int,
    chunk_total: int,
    chunk: bytes,
    *,
    kind: MediaKind,
    filename: str,
    content_type: str,
    owner: str,
    device_id: str | None,
) -> dict | MediaUpload:
    if chunk_total < 1 or chunk_index < 0 or chunk_index >= chunk_total:
        raise HTTPException(400, "Invalid chunk index")
    if not chunk and chunk_index < chunk_total - 1:
        raise HTTPException(400, "Chunk is empty")
    cap = caps_for_kind(kind)
    chunk_dir = chunks_root() / upload_id
    chunk_dir.mkdir(parents=True, exist_ok=True)
    part_path = chunk_dir / f"{chunk_index:06d}.part"
    if not part_path.exists():
        with part_path.open("wb") as handle:
            handle.write(chunk)
    meta_key = f"{upload_id}:meta"
    with database() as db:
        meta = get(db, CHUNK_RECORD_KIND, meta_key) or {
            "upload_id": upload_id,
            "kind": kind,
            "filename": _safe_name(filename),
            "content_type": (content_type or "application/octet-stream")[:100],
            "owner": owner,
            "device_id": device_id,
            "chunk_total": chunk_total,
            "received": [],
            "bytes": 0,
        }
        if meta["chunk_total"] != chunk_total:
            raise HTTPException(409, "Chunk total mismatch")
        if chunk_index not in meta["received"]:
            meta["bytes"] = int(meta.get("bytes") or 0) + len(chunk)
            meta["received"].append(chunk_index)
        if meta["bytes"] > cap:
            _cleanup_chunks(upload_id)
            raise HTTPException(413, f"Upload exceeds {kind} limit ({cap} bytes)")
        put(db, CHUNK_RECORD_KIND, meta_key, meta)
        received = sorted(set(meta["received"]))
        if len(received) < chunk_total:
            return {
                "upload_id": upload_id,
                "kind": kind,
                "chunk_index": chunk_index,
                "chunk_total": chunk_total,
                "received": len(received),
                "complete": False,
            }
    parts = sorted(chunk_dir.glob("*.part"))
    if len(parts) != chunk_total:
        raise HTTPException(400, "Missing chunks")
    assembled = bytearray()
    for part in parts:
        assembled.extend(part.read_bytes())
    _cleanup_chunks(upload_id)
    with database() as db:
        delete(db, CHUNK_RECORD_KIND, meta_key)
    return save_upload(
        bytes(assembled),
        kind=kind,
        filename=filename,
        content_type=content_type,
        owner=owner,
        device_id=device_id,
        upload_id=upload_id,
    )


def _cleanup_chunks(upload_id: str) -> None:
    chunk_dir = chunks_root() / upload_id
    if chunk_dir.exists():
        for part in chunk_dir.glob("*"):
            part.unlink(missing_ok=True)
        chunk_dir.rmdir()


def paths_for_ids(upload_ids: list[str], *, device_id: str | None, owner: bool) -> list[str]:
    paths: list[str] = []
    for upload_id in upload_ids:
        item = require_upload(upload_id)
        assert_access(item, owner_key=owner, device_id=device_id)
        path = blob_path(upload_id)
        if not path.is_file():
            raise HTTPException(404, "Upload not found")
        paths.append(str(path.resolve()))
    return paths


def register_analyze_artifact(upload_id: str, payload: dict) -> str:
    artifact_id = str(uuid.uuid4())
    record = {
        "id": artifact_id,
        "upload_id": upload_id,
        "created_at": time.time(),
        **payload,
    }
    with database() as db:
        put(db, ANALYZE_ARTIFACT_KIND, artifact_id, record)
    return artifact_id
