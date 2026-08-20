from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..agent.loop import AGENT

router = APIRouter(prefix="/api/voice", tags=["voice"])


class VoiceIn(BaseModel):
    text: str
    autonomy: str | None = None


@router.post("/command")
async def voice_command(body: VoiceIn):
    """Ingest transcribed speech. STT/TTS can be added later without changing the agent."""
    task = await AGENT.create_task(body.text, body.autonomy)
    return {"task_id": task.id, "status": task.status}
