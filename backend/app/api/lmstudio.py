from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..inference.lmstudio_catalog import (
    AXIS_KEYS,
    apply_grade_override,
    build_catalog,
    get_graded_profile,
    select_catalog_profile,
    set_profile_pinned,
)

router = APIRouter(prefix="/api/lmstudio", tags=["lmstudio"])


class PinRequest(BaseModel):
    pinned: bool


class GradeOverrideRequest(BaseModel):
    overall: float | None = None
    axes: dict[str, float] | None = None


@router.get("/catalog")
async def get_catalog(show_hidden: bool = False):
    return build_catalog(show_hidden=show_hidden)


@router.post("/catalog/{profile_id}/pin")
async def pin_profile(profile_id: str, body: PinRequest):
    try:
        set_profile_pinned(profile_id, body.pinned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    profile = get_graded_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="catalog profile not found")
    return {"ok": True}


@router.post("/catalog/{profile_id}/override")
async def override_profile(profile_id: str, body: GradeOverrideRequest):
    if body.axes:
        unknown = [key for key in body.axes if key not in AXIS_KEYS]
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"unknown axis keys: {', '.join(unknown)}",
            )
    try:
        profile = apply_grade_override(
            profile_id,
            overall=body.overall,
            axes=body.axes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return profile


@router.post("/catalog/{profile_id}/select")
async def select_profile(profile_id: str):
    try:
        return select_catalog_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
