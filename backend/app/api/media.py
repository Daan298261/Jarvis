from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..auth import require_owner_private_key
from ..media.analyze import analyze_upload
from ..media.studio import attach_studio_take
from ..media.store import (
    MediaKind,
    assert_access,
    blob_path,
    caps_for_kind,
    detect_kind,
    get_upload,
    ingest_chunk,
    require_upload,
    save_upload,
)
from ..mobile import identity

router = APIRouter(prefix="/api/media", tags=["media"])
Owner = Depends(require_owner_private_key)


class AnalyzeBody(BaseModel):
    actions: list[str] = Field(default_factory=list, max_length=8)


class StudioBody(BaseModel):
    operation: str | None = Field(default=None, max_length=40)


def _parse_chunk_headers(request: Request) -> tuple[str | None, int | None, int | None, MediaKind | None]:
    upload_id = request.headers.get("x-jarvis-upload-id", "").strip() or None
    raw_index = request.headers.get("x-jarvis-chunk-index", "").strip()
    raw_total = request.headers.get("x-jarvis-chunk-total", "").strip()
    kind_raw = request.headers.get("x-jarvis-upload-kind", "").strip().lower()
    chunk_index = int(raw_index) if raw_index.isdigit() else None
    chunk_total = int(raw_total) if raw_total.isdigit() else None
    kind: MediaKind | None = None
    if kind_raw in {"image", "video", "audio", "file"}:
        kind = kind_raw  # type: ignore[assignment]
    return upload_id, chunk_index, chunk_total, kind


def _project_id_from_request(request: Request, form: object | None = None) -> str | None:
    raw = request.headers.get("x-jarvis-project-id", "").strip()
    if not raw and form is not None and hasattr(form, "get"):
        raw = str(form.get("project_id") or "").strip()
    return raw or None


@router.get("/uploads/caps")
async def upload_caps(_owner=Owner):
    return {
        "image_max_bytes": caps_for_kind("image"),
        "file_max_bytes": caps_for_kind("file"),
        "video_max_bytes": caps_for_kind("video"),
        "audio_max_bytes": caps_for_kind("audio"),
        "chunked_video_required": True,
    }


@router.post("/uploads")
async def create_upload(request: Request, _owner=Owner):
    upload_id, chunk_index, chunk_total, header_kind = _parse_chunk_headers(request)
    content_header = request.headers.get("content-type", "")
    form_kind: str | None = None
    form_project_id: str | None = None
    filename = request.headers.get("x-filename") or "upload"
    content_type = content_header or "application/octet-stream"
    data = bytearray()
    form = None
    if "multipart/form-data" in content_header:
        form = await request.form()
        form_kind = str(form.get("kind") or "").strip().lower() or None
        form_project_id = str(form.get("project_id") or "").strip() or None
        upload = form.get("file")
        if upload is not None and hasattr(upload, "read"):
            filename = getattr(upload, "filename", None) or filename
            content_type = getattr(upload, "content_type", None) or content_type
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                data.extend(chunk)
        else:
            raise HTTPException(400, "Upload is empty")
    else:
        async for chunk in request.stream():
            data.extend(chunk)
    resolved_kind: MediaKind
    if form_kind in {"image", "video", "audio", "file"}:
        resolved_kind = form_kind  # type: ignore[assignment]
    else:
        resolved_kind = header_kind or detect_kind(content_type, filename)
    if len(data) > caps_for_kind(resolved_kind):
        raise HTTPException(413, f"Upload exceeds {resolved_kind} limit")

    media_project_id = _project_id_from_request(request, form) or form_project_id

    if upload_id and chunk_index is not None and chunk_total is not None:
        result = ingest_chunk(
            upload_id,
            chunk_index,
            chunk_total,
            bytes(data),
            kind=resolved_kind,
            filename=filename,
            content_type=content_type,
            owner="desktop",
            device_id=None,
            project_id=media_project_id,
        )
        if isinstance(result, dict):
            return result
        return result.to_public()

    item = save_upload(
        bytes(data),
        kind=resolved_kind,
        filename=filename,
        content_type=content_type,
        owner="desktop",
        project_id=media_project_id,
    )
    return item.to_public()


@router.get("/uploads/{upload_id}")
async def get_upload_meta(upload_id: uuid.UUID, _owner=Owner):
    item = require_upload(str(upload_id))
    assert_access(item, owner_key=True, device_id=None)
    return item.to_public()


@router.get("/uploads/{upload_id}/download")
async def download_upload(upload_id: uuid.UUID, _owner=Owner):
    item = require_upload(str(upload_id))
    assert_access(item, owner_key=True, device_id=None)
    path = blob_path(str(upload_id))
    if not path.is_file():
        raise HTTPException(404, "Upload not found")
    return FileResponse(path, filename=item.name, media_type=item.content_type)


@router.post("/uploads/{upload_id}/analyze")
async def analyze(upload_id: uuid.UUID, body: AnalyzeBody | None = None, _owner=Owner):
    item = require_upload(str(upload_id))
    assert_access(item, owner_key=True, device_id=None)
    return await analyze_upload(item, (body.actions if body else None))


@router.post("/uploads/{upload_id}/studio")
async def studio(upload_id: uuid.UUID, body: StudioBody | None = None, _owner=Owner):
    item = require_upload(str(upload_id))
    assert_access(item, owner_key=True, device_id=None)
    return attach_studio_take(item, body.operation if body else None)


async def companion_ingest(request: Request, device: dict) -> dict:
    upload_id, chunk_index, chunk_total, header_kind = _parse_chunk_headers(request)
    filename = request.headers.get("x-filename", "attachment")[:200]
    content_type = request.headers.get("content-type", "application/octet-stream")[:100]
    kind_header = request.headers.get("x-jarvis-upload-kind", "").strip().lower()
    media_project_id = _project_id_from_request(request)
    kind: MediaKind | None = None
    if kind_header in {"image", "video", "audio", "file"}:
        kind = kind_header  # type: ignore[assignment]
    resolved_kind = kind or header_kind or detect_kind(content_type, filename)
    upload_id = upload_id or str(uuid.uuid4())

    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > caps_for_kind(resolved_kind):
            raise HTTPException(413, f"Attachment exceeds {resolved_kind} limit")
    if not data and chunk_index is None:
        raise HTTPException(400, "Attachment is empty")

    if chunk_index is not None and chunk_total is not None:
        result = ingest_chunk(
            upload_id,
            chunk_index,
            chunk_total,
            bytes(data),
            kind=resolved_kind,
            filename=filename,
            content_type=content_type,
            owner=device["id"],
            device_id=device["id"],
            project_id=media_project_id,
        )
        if isinstance(result, dict):
            return result
        public = result.to_public()
        public["device_id"] = device["id"]
        return public

    item = save_upload(
        bytes(data),
        kind=resolved_kind,
        filename=filename,
        content_type=content_type,
        owner=device["id"],
        device_id=device["id"],
        upload_id=upload_id if upload_id else None,
        project_id=media_project_id,
    )
    public = item.to_public()
    public["device_id"] = device["id"]
    return public


def companion_download(attachment_id: str, device: dict):
    item = require_upload(attachment_id)
    assert_access(item, owner_key=False, device_id=device["id"])
    path = blob_path(attachment_id)
    if not path.is_file():
        raise HTTPException(404, "Attachment not found")
    return FileResponse(path, filename=item.name, media_type=item.content_type)
