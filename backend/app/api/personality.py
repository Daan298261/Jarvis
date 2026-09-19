from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..persona.session_personality import personality_api_payload, set_active_personality

router = APIRouter(prefix="/api/personality", tags=["personality"])


class PersonalitySelectBody(BaseModel):
    personality_id: str = Field(min_length=1, max_length=32)


@router.get("")
async def get_personality():
    return personality_api_payload()


@router.post("")
async def select_personality(body: PersonalitySelectBody):
    pack = set_active_personality(body.personality_id)
    payload = personality_api_payload()
    payload["selected"] = pack.id
    return payload
