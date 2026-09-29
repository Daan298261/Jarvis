"""BlackGrid Multimedia Studio API — ComfyUI + HR Endless Sampler workbench."""

from __future__ import annotations

from typing import Any

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..auth import require_owner_private_key
from ..studio import blackgrid_runtime

router = APIRouter(prefix="/api/blackgrid", tags=["blackgrid"])
Owner = Depends(require_owner_private_key)


class EnableBody(BaseModel):
    enabled: bool


class SubmitJobBody(BaseModel):
    prompt: str = Field(min_length=1, max_length=200_000)
    chunk_frames: int = Field(default=39, ge=5, le=120)
    reference_images: list[str] = Field(default_factory=list)


@router.get("/status")
async def get_status(_owner=Owner) -> dict[str, Any]:
    snap = await blackgrid_runtime.status()
    caps = await blackgrid_runtime.studio_capabilities_async()
    return {"module": snap, "capabilities": caps}


@router.get("/capabilities")
async def get_capabilities(_owner=Owner) -> dict[str, Any]:
    return await blackgrid_runtime.studio_capabilities_async()


@router.post("/install")
async def install(_owner=Owner) -> dict[str, Any]:
    result = await blackgrid_runtime.install_and_enable()
    if not result.get("ok") and result.get("install_status") == "error":
        raise HTTPException(status_code=400, detail=result.get("detail") or "Install failed")
    return result


@router.post("/start")
async def start(_owner=Owner) -> dict[str, Any]:
    result = await blackgrid_runtime.start()
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=result.get("detail") or "Start failed")
    return result


@router.post("/stop")
async def stop(_owner=Owner) -> dict[str, Any]:
    return await blackgrid_runtime.stop()


@router.post("/enable")
async def enable(body: EnableBody, _owner=Owner) -> dict[str, Any]:
    from .. import config as app_config

    s = app_config.load_settings()
    s.blackgrid.enabled = body.enabled
    app_config.save_settings(s)
    if body.enabled and not (blackgrid_runtime.comfy_root() / "main.py").is_file():
        return await blackgrid_runtime.install_and_enable()
    if body.enabled:
        return await blackgrid_runtime.start()
    return await blackgrid_runtime.stop()


@router.post("/jobs")
async def submit_job(body: SubmitJobBody, _owner=Owner) -> dict[str, Any]:
    try:
        return await blackgrid_runtime.submit_hr_endless_job(
            body.prompt,
            chunk_frames=body.chunk_frames,
            reference_images=body.reference_images,
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/jobs")
async def list_jobs(_owner=Owner) -> dict[str, Any]:
    return {"jobs": await blackgrid_runtime.list_jobs()}


@router.get("/outputs")
async def list_outputs(_owner=Owner) -> dict[str, Any]:
    return {"outputs": await blackgrid_runtime.list_outputs()}


@router.get("/output-file")
async def output_file(path: str, _owner=Owner):
    root = blackgrid_runtime.output_dir().resolve()
    candidate = Path(path).expanduser().resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Path is outside ComfyUI output") from exc
    if not candidate.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(candidate)


@router.get("/open-urls")
async def open_urls(_owner=Owner) -> dict[str, Any]:
    """Primary tool entry: portal workbench + ComfyUI (open in new tab)."""
    snap = await blackgrid_runtime.status()
    comfy = str(snap.get("comfy_ui_url") or blackgrid_runtime._base_url())
    return {
        "workbench_url": "/studio/blackgrid",
        "comfy_ui_url": comfy,
        "template_workflow": "Jarvis-HR-Endless-Sampler.json",
        "primary_engine": "hr-endless-sampler",
    }
