"""GET/PUT /api/named-personas — RFC-0137 catalog. Not session personality."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..inference.hotswap import activate_runtime_profile, parse_runtime_endpoint
from ..inference.runtime_profiles import get_runtime_profile
from ..persona.named_persona import (
    NamedPersonaBindError,
    apply_main_persona,
    attach_specialist,
    persist_persona_preferences,
    public_state,
    resolve_persona_id,
    update_appearance,
)
from ..inference.ollama_runtime import ensure_local_ollama
from ..persona.persona_brain import brain_runtime_name_for_persona, reflex_verify_brain_runtime

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/named-personas", tags=["named-personas"])


class AppearanceIn(BaseModel):
    voice_profile_id: str | None = None
    pitch: float | None = None
    speaking_rate: float | None = None
    volume: float | None = None
    orb_color: str | None = None
    accent_color: str | None = None
    glow: float | None = None
    animation: float | None = None
    scale: float | None = None
    specialists_auto_speak: bool | None = None


class NamedPersonaPut(BaseModel):
    id: str = Field(min_length=1, max_length=40)
    task_id: str | None = Field(default=None, max_length=80)
    as_specialist: bool = False
    reset: bool = False
    appearance: AppearanceIn | None = None
    activate_brain: bool = True
    apply: bool = True
    set_as_default: bool = False
    pin: bool | None = None


async def _maybe_activate_persona_brain(raw_persona_id: str) -> None:
    try:
        persona_id = resolve_persona_id(raw_persona_id, required=True)
    except NamedPersonaBindError:
        return
    runtime_name = brain_runtime_name_for_persona(persona_id)
    if not runtime_name:
        return
    profile = get_runtime_profile(runtime_name) or get_runtime_profile(f"recommended-{runtime_name}")
    if profile is None or not profile.enabled:
        return
    if not reflex_verify_brain_runtime(persona_id=persona_id, runtime_name=runtime_name):
        logger.info(
            "persona_brain_reflex_declined persona=%s runtime=%s",
            persona_id,
            runtime_name,
        )
        return
    if (profile.provider or "").strip().lower() == "ollama":
        host, port = parse_runtime_endpoint(profile.endpoint)
        boot = await ensure_local_ollama(host=host, port=port, model=profile.model)
        if not boot.get("ok"):
            logger.warning(
                "persona_brain_ollama_prepare_failed persona=%s detail=%s",
                persona_id,
                boot.get("detail"),
            )
            return
    try:
        await activate_runtime_profile(profile, force=True)
    except Exception as exc:
        logger.warning(
            "persona_brain_activate_failed persona=%s runtime=%s detail=%s",
            persona_id,
            runtime_name,
            str(exc)[:240],
        )


def _http(exc: NamedPersonaBindError) -> HTTPException:
    status = 400 if exc.code in {"unknown", "invalid"} else 409
    return HTTPException(
        status,
        {"error": exc.code, "detail": exc.detail, "profile_id": exc.profile_id},
    )


@router.get("")
async def get_named_personas() -> dict:
    return public_state()


@router.put("")
async def put_named_personas(body: NamedPersonaPut) -> dict:
    patch = body.appearance.model_dump(exclude_none=True) if body.appearance is not None else None
    try:
        if body.as_specialist:
            if not (body.task_id or "").strip():
                raise HTTPException(400, "task_id is required when as_specialist is true")
            if body.reset or patch:
                update_appearance(body.id, patch, reset=body.reset)
            return await attach_specialist(body.id, body.task_id or "")
        if body.set_as_default or body.pin is not None:
            persist_persona_preferences(
                body.id,
                set_as_default=body.set_as_default,
                pin=body.pin,
            )
        if body.apply:
            apply_main_persona(body.id, reset=body.reset)
            if patch:
                update_appearance(body.id, patch, reset=False)
            if body.activate_brain:
                await _maybe_activate_persona_brain(body.id)
        elif patch:
            update_appearance(body.id, patch, reset=body.reset)
        return public_state()
    except NamedPersonaBindError as exc:
        raise _http(exc) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
