"""HUD "Unload model": release every model ANZU loaded, verified, with a per-backend result.

Separate from the dropdown's single-model ``POST /api/model/unload`` (unchanged).
Status codes: 200 every ANZU-loaded model released and verified; 409 refused, nothing
touched (request or load in flight, task running, nothing to unload); 502 a backend
failed to release or could not be verified, with its own detail.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..inference.keep_warm_release import release_models

router = APIRouter(prefix="/api/model", tags=["model"])


@router.post("/unload-all")
async def unload_all_models():
    result = await release_models("manual")
    if result["refused"]:
        raise HTTPException(status_code=409, detail=result["reason"])
    if not result["ok"]:
        raise HTTPException(status_code=502, detail=result["reason"])
    return result
