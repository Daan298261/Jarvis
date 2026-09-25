"""GET/PUT /api/named-personas — RFC-0137 catalog. Not session personality."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..persona.named_persona import (
    NamedPersonaBindError,
    apply_main_persona,
    attach_specialist,
    public_state,
    update_appearance,
)

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
        apply_main_persona(body.id, reset=body.reset)
        if patch:
            update_appearance(body.id, patch, reset=False)
        return public_state()
    except NamedPersonaBindError as exc:
        raise _http(exc) from exc
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
