from __future__ import annotations

import json
import logging

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
from ..tts.pack_install import install_voice_pack
from ..tts.engines import resolve_engine_id
from ..workers.voice import synthesize_speech_result

router = APIRouter(prefix="/api/voice-profiles", tags=["voice-profiles"])
logger = logging.getLogger(__name__)


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


@router.post("/{profile_id}/install")
async def install_voice_profile_pack(profile_id: str):
    if contains_forbidden_ip_term(profile_id):
        raise HTTPException(
            status_code=400,
            detail="profile_id contains a forbidden copyrighted-character or trademark term",
        )
    catalog = get_catalog()
    profile = catalog.get(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Unknown voice profile: {profile_id}")
    try:
        result = install_voice_pack(profile)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if not result.ok:
        raise HTTPException(status_code=409, detail=result.detail)
    active_id = get_active_voice_profile_id()
    items = catalog.list_profiles(active_id)
    listed = next((item for item in items if item.id == profile_id), None)
    return {
        "profile_id": profile_id,
        "installed": True,
        "detail": result.detail,
        "pack_path": result.pack_path,
        "profile": listed.model_dump() if listed else None,
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
    requested_engine = resolve_engine_id(profile.tts)
    event = {
        "profile_id": profile_id,
        "requested_engine": requested_engine,
        "model_id": profile.tts.model_id,
        "speaker_ref": profile.tts.speaker_ref,
    }
    logger.info("voice_preview_requested %s", json.dumps(event, sort_keys=True))
    try:
        result = await synthesize_speech_result(
            text,
            voice_profile_id=profile_id,
            exact_profile=True,
        )
    except RuntimeError as exc:
        logger.warning(
            "voice_preview_failed %s",
            json.dumps({**event, "error": str(exc)}, sort_keys=True),
        )
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if result.profile_id != profile_id or result.engine_id != requested_engine:
        detail = (
            f"Preview returned {result.engine_id or 'no engine'} for {result.profile_id or 'no profile'} "
            f"instead of selected {requested_engine} profile {profile_id}."
        )
        logger.warning(
            "voice_preview_failed %s",
            json.dumps({**event, "actual_engine": result.engine_id, "error": detail}, sort_keys=True),
        )
        raise HTTPException(status_code=503, detail=detail)
    if len(result.audio) < 44 or not result.audio.startswith(b"RIFF"):
        detail = "The selected voice produced an empty or invalid WAV preview."
        logger.warning(
            "voice_preview_failed %s",
            json.dumps({**event, "actual_engine": result.engine_id, "error": detail}, sort_keys=True),
        )
        raise HTTPException(status_code=503, detail=detail)
    logger.info(
        "voice_preview_succeeded %s",
        json.dumps(
            {
                **event,
                "actual_engine": result.engine_id,
                "model_id": result.model_id,
                "speaker_ref": result.speaker_ref,
                "bytes": len(result.audio),
            },
            sort_keys=True,
        ),
    )
    return Response(
        content=result.audio,
        media_type="audio/wav",
        headers={
            "X-Jarvis-TTS-Engine": result.engine_id,
            "X-Jarvis-Voice-Profile": result.profile_id,
            "X-Jarvis-TTS-Model": result.model_id,
            "X-Jarvis-TTS-Voice": result.speaker_ref,
        },
    )
