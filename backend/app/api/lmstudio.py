from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..inference.lmstudio_catalog import (
    AXIS_KEYS,
    build_catalog,
    discovery_payload,
    select_catalog_profile,
    set_profile_override,
    set_profile_pin,
)

router = APIRouter(prefix="/api/lmstudio", tags=["lmstudio"])


class PinBody(BaseModel):
    pinned: bool


class OverrideBody(BaseModel):
    overall: float | None = None
    axes: dict[str, int] | None = Field(default=None)


@router.get("/catalog")
async def get_catalog(show_hidden: bool = False):
    return build_catalog(show_hidden=show_hidden)


@router.post("/catalog/{profile_id}/pin")
async def pin_catalog_profile(profile_id: str, body: PinBody):
    try:
        set_profile_pin(profile_id, body.pinned)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True}


@router.post("/catalog/{profile_id}/override")
async def override_catalog_profile(profile_id: str, body: OverrideBody):
    axes = body.axes or {}
    invalid = [key for key in axes if key not in AXIS_KEYS]
    if invalid:
        raise HTTPException(status_code=400, detail=f"invalid axis keys: {', '.join(invalid)}")
    try:
        return set_profile_override(profile_id, overall=body.overall, axes=axes or None)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/catalog/{profile_id}/select")
async def select_profile(profile_id: str):
    try:
        profile = select_catalog_profile(profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return profile.as_dict()


@router.get("/discovery")
async def get_discovery():
    return discovery_payload()
