from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..agent.loop import AGENT
from ..workers.voice import synthesize_speech, transcribe_audio, voice_status

router = APIRouter(prefix="/api/voice", tags=["voice"])


class VoiceIn(BaseModel):
    text: str
    autonomy: str | None = None


class SpeakIn(BaseModel):
    text: str


@router.get("/status")
async def get_voice_status():
    return voice_status()


@router.post("/command")
async def voice_command(body: VoiceIn):
    """Create a task from already-transcribed speech (or typed text)."""
    text = (body.text or "").strip()
    if not text:
        raise HTTPException(400, "text is required")
    task = await AGENT.create_task(text, body.autonomy)
    return {"task_id": task.id, "status": task.status, "transcript": text}


@router.post("/listen")
async def voice_listen(audio: UploadFile = File(...), autonomy: str | None = Form(None)):
    """Transcribe local audio with Whisper (when installed) and create a task."""
    data = await audio.read()
    if not data:
        raise HTTPException(400, "audio is required")
    try:
        transcript = await transcribe_audio(data, audio.filename or "audio.webm")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    task = await AGENT.create_task(transcript, autonomy)
    return {
        "task_id": task.id,
        "status": task.status,
        "transcript": transcript,
    }


@router.post("/transcribe")
async def voice_transcribe(audio: UploadFile = File(...)):
    data = await audio.read()
    if not data:
        raise HTTPException(400, "audio is required")
    try:
        transcript = await transcribe_audio(data, audio.filename or "audio.webm")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return {"transcript": transcript}


@router.post("/speak")
async def voice_speak(body: SpeakIn):
    try:
        wav = await synthesize_speech(body.text)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(content=wav, media_type="audio/wav")
