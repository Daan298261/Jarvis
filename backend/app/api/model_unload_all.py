"""HUD "Unload model": release every model ANZU loaded, verified, with a per-model result.

Separate from the dropdown's single-model ``POST /api/model/unload`` (unchanged).
Status codes (RFC-0242 "Unload-all"): 200 every ANZU-loaded model released and verified; 207 some
failed or could not be verified (the body names every model and why; never rendered as success);
409 refused, nothing attempted (request or load in flight, task running, nothing to unload).
Body: ``{results: [{model, backend, via, verified, error}], released, failed, skipped: [{model, reason}],
snapshot, ...}``.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from ..inference.keep_warm_release import release_models

router = APIRouter(prefix="/api/model", tags=["model"])


@router.post("/unload-all")
async def unload_all_models():
    result = await release_models("manual")
    if result["refused"]:
        raise HTTPException(status_code=409, detail=result["reason"])
    from ..inference.hotswap import runtime_activation_snapshot

    result["snapshot"] = runtime_activation_snapshot()
    return JSONResponse(jsonable_encoder(result), status_code=200 if result["ok"] else 207)
