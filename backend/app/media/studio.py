from __future__ import annotations

from fastapi import HTTPException

from ..mobile import service
from .store import MediaUpload, update_upload_record


def attach_studio_take(upload: MediaUpload, operation: str | None = None) -> dict:
    caps = service.studio_capabilities()
    if not caps.get("available"):
        raise HTTPException(
            503,
            caps.get("detail") or "Studio backend not connected.",
        )
    op = (operation or upload.kind).strip().lower()
    allowed = {item.lower() for item in caps.get("operations") or []}
    if op not in allowed and "takes" not in allowed:
        raise HTTPException(503, "Studio backend does not accept this media type yet.")
    payload = {
        "status": "queued",
        "operation": op,
        "upload_id": upload.id,
        "kind": upload.kind,
        "detail": "Take registered; generation engines are not connected (RFC-0096/0097).",
    }
    update_upload_record(upload.id, studio=payload)
    return {"ok": True, "studio": payload, "capabilities": caps}
