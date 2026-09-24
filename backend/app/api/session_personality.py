from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..persona.session_personality import active_mode, list_modes, manual_lock, maybe_switch_from_owner_message, set_active_mode, set_manual_lock

router = APIRouter(prefix="/api/session-personality", tags=["session-personality"])


class ModeIn(BaseModel):
    mode: str = Field(min_length=1, max_length=32)
    manual: bool = True


class DetectIn(BaseModel):
    message: str = Field(min_length=1, max_length=8000)


@router.get("")
async def get_session_personality() -> dict:
    mode = active_mode()
    return {"active": mode.as_dict(), "modes": list_modes(), "manual_lock": manual_lock()}


@router.put("")
async def put_session_personality(body: ModeIn) -> dict:
    try:
        mode = set_active_mode(body.mode)
        set_manual_lock(body.manual)
    except KeyError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {"active": mode.as_dict(), "manual_lock": manual_lock()}


@router.post("/detect")
async def detect_session_personality(body: DetectIn) -> dict:
    switched = maybe_switch_from_owner_message(body.message)
    mode = active_mode()
    return {"active": mode.as_dict(), "switched": switched.as_dict() if switched else None}


@router.post("/auto")
async def enable_auto_personality() -> dict:
    set_manual_lock(False)
    return {"active": active_mode().as_dict(), "manual_lock": False}
