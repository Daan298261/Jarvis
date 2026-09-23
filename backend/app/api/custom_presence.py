"""RFC-0138 custom presence generation and preset APIs."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ..presence.custom_ui import (
    ORB_CONSTRAINT,
    discard_preview,
    get_job,
    public_custom_presence_state,
    run_custom_presence_job,
    save_preset_from_job,
    set_default_preset,
    delete_preset,
    clear_active_preset,
    _job_dict,
)

router = APIRouter(prefix="/api/custom-presence", tags=["custom-presence"])


class JobJsonIn(BaseModel):
    prompt_text: str | None = None


class SavePresetIn(BaseModel):
    job_id: str = Field(min_length=8, max_length=64)
    name: str = Field(default="", max_length=80)
    set_default: bool = False


class DefaultPresetIn(BaseModel):
    preset_id: str = Field(min_length=1, max_length=64)


@router.get("")
async def get_custom_presence() -> dict:
    return public_custom_presence_state()


@router.get("/constraint")
async def get_orb_constraint() -> dict:
    return {"constraint": ORB_CONSTRAINT}


@router.post("/jobs")
async def post_custom_presence_job(request: Request) -> dict:
    content_type = (request.headers.get("content-type") or "").lower()
    text = ""
    image_bytes: bytes | None = None
    filename = ""
    file_ct = ""
    if "multipart/form-data" in content_type:
        form = await request.form()
        text = str(form.get("prompt_text") or "").strip()
        upload = form.get("image")
        if upload is not None and hasattr(upload, "read"):
            image_bytes = await upload.read()
            filename = getattr(upload, "filename", None) or "upload.jpg"
            file_ct = getattr(upload, "content_type", None) or ""
    else:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            text = str(payload.get("prompt_text") or "").strip()
        elif isinstance(payload, str):
            text = payload.strip()
    content_type = file_ct
    if not text and not image_bytes:
        raise HTTPException(400, {"error": {"code": "invalid_input", "message": "text or image required"}})
    try:
        job = await run_custom_presence_job(
            prompt_text=text,
            image_bytes=image_bytes,
            image_filename=filename,
            image_content_type=content_type,
        )
    except ValueError as exc:
        if str(exc) == "payload_too_large":
            raise HTTPException(413, "image exceeds size cap") from exc
        if str(exc) == "invalid_input":
            raise HTTPException(400, {"error": {"code": "invalid_input", "message": "invalid image"}}) from exc
        raise HTTPException(400, str(exc)) from exc
    return _job_dict(job)


@router.get("/jobs/{job_id}")
async def get_custom_presence_job(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, "unknown job")
    return _job_dict(job)


@router.post("/presets")
async def post_save_preset(body: SavePresetIn) -> dict:
    try:
        return save_preset_from_job(body.job_id, body.name, set_default=body.set_default)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.put("/default")
async def put_default_preset(body: DefaultPresetIn) -> dict:
    try:
        return set_default_preset(body.preset_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.delete("/presets/{preset_id}")
async def remove_preset(preset_id: str) -> dict:
    try:
        return delete_preset(preset_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/active/clear")
async def post_clear_active() -> dict:
    return clear_active_preset()


@router.post("/jobs/{job_id}/discard")
async def post_discard_preview(job_id: str) -> dict:
    discard_preview(job_id)
    return {"discarded": True}
