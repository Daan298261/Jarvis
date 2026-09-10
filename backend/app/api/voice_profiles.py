from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response

from ..voice_profiles.catalog import (
    get_active_voice_profile,
    get_active_voice_profile_id,
    get_catalog,
    set_active_voice_profile_id,
)
from ..voice_profiles.ip_guard import contains_forbidden_ip_term
from ..voice_profiles.schema import ActiveVoiceProfileIn, ActiveVoiceProfileOut
from ..workers.voice import synthesize_speech

router = APIRouter(prefix="/api/voice-profiles", tags=["voice-profiles"])


@router.get("")
async def list_voice_profiles():
    active_id = get_active_voice_profile_id()
    catalog = get_catalog()
    profiles = catalog.list_profiles(active_id)
    return {
        "active_voice_profile_id": active_id,
        "profiles": [profile.model_dump() for profile in profiles],
    }


@router.get("/active")
async def get_active_voice_profile_endpoint():
    active_id = get_active_voice_profile_id()
    catalog = get_catalog()
    items = catalog.list_profiles(active_id)
    active_item = next((item for item in items if item.id == active_id), None)
    return ActiveVoiceProfileOut(voice_profile_id=active_id, profile=active_item)


@router.put("/active")
async def set_active_voice_profile(body: ActiveVoiceProfileIn):
    if contains_forbidden_ip_term(body.voice_profile_id):
        raise HTTPException(
            status_code=400,
            detail="voice_profile_id contains a forbidden copyrighted-character or trademark term",
        )
    try:
        profile = set_active_voice_profile_id(body.voice_profile_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        try:
            payload = json.loads(str(exc))
        except json.JSONDecodeError:
            payload = {"detail": str(exc)}
        raise HTTPException(status_code=409, detail=payload) from exc
    return {
        "voice_profile_id": body.voice_profile_id,
        "profile": profile.model_dump(),
    }


@router.post("/{profile_id}/preview")
async def preview_voice_profile(profile_id: str):
    if contains_forbidden_ip_term(profile_id):
        raise HTTPException(
            status_code=400,
            detail="profile_id contains a forbidden copyrighted-character or trademark term",
        )
    catalog = get_catalog()
    profile = catalog.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown voice profile: {profile_id}")

    items = catalog.list_profiles(get_active_voice_profile_id())
    listed = next((item for item in items if item.id == profile_id), None)
    if listed is None or not listed.available:
        raise HTTPException(
            status_code=409,
            detail={
                "error": listed.unavailable_reason if listed else "unavailable",
                "detail": listed.install_hint if listed else "Voice profile is not available.",
                "profile_id": profile_id,
            },
        )

    text = (profile.sample_utterance or "At your service.").strip()
    try:
        wav = await synthesize_speech(text, voice_profile_id=profile_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(content=wav, media_type="audio/wav")
