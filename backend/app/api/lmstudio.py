from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import load_settings
from ..inference.default_candidates import (
    PERSONALITY_PRESETS,
    RECOMMENDED_16GB_STACK,
    TTS_CANDIDATES,
    list_model_candidates,
)
from ..inference.hotswap import activate_runtime_profile
from ..inference.lmstudio_catalog import (
    AXIS_KEYS,
    build_catalog,
    discovery_payload,
    select_catalog_profile,
    set_profile_override,
    set_profile_pin,
)
from ..inference.manager import MANAGER

router = APIRouter(prefix="/api/lmstudio", tags=["lmstudio"])


class PinBody(BaseModel):
    pinned: bool


class OverrideBody(BaseModel):
    overall: float | None = None
    axes: dict[str, int] | None = Field(default=None)


@router.get("/catalog")
async def get_catalog(show_hidden: bool = False):
    return build_catalog(show_hidden=show_hidden)


@router.get("/candidates")
async def get_inference_candidates(role: str | None = None):
    """Return RFC-0063 candidates without promoting them to active runtimes.

    The catalog is advisory: actual promotion remains gated by the local Jarvis
    benchmark so an externally well-regarded model cannot silently replace the
    working primary on reputation alone.
    """

    allowed_roles = {"micro", "small", "primary", "presentation", "expert", "lab"}
    normalized_role = None
    if role:
        normalized_role = role.strip().lower().replace("_", "-")
        if normalized_role not in allowed_roles:
            raise HTTPException(status_code=400, detail=f"unknown candidate role: {role}")

    candidates = list_model_candidates(normalized_role) if normalized_role else list_model_candidates()
    return {
        "candidates": [candidate.as_dict() for candidate in candidates],
        "recommended_16gb_stack": RECOMMENDED_16GB_STACK,
        "tts_candidates": [candidate.as_dict() for candidate in TTS_CANDIDATES.values()],
        "personality_presets": [preset.as_dict() for preset in PERSONALITY_PRESETS.values()],
        "promotion_policy": "benchmark-required",
    }


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
    try:
        await activate_runtime_profile(profile)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:500]) from exc
    settings = load_settings()
    payload = profile.as_dict()
    payload["load"] = await MANAGER.snapshot(settings)
    return payload


@router.get("/discovery")
async def get_discovery():
    return discovery_payload()
