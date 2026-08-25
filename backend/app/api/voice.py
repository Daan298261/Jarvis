from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel

from ..agent.loop import AGENT
from ..config import load_settings
from ..voice import transcribe_wav, voice_status
from ..voice.tts import synthesize_wav

router = APIRouter(prefix="/api/voice", tags=["voice"])
MAX_AUDIO = 8 * 1024 * 1024


class VoiceIn(BaseModel):
    text: str = ""
    autonomy: str | None = None
    execution_mode: str | None = None


class SpeakIn(BaseModel):
    text: str


@router.get("")
@router.get("/status")
async def voice_info():
    return voice_status()


@router.post("/transcribe")
async def transcribe(audio: UploadFile = File(...)):
    text = await _transcribe_upload(audio)
    return {"text": text}


@router.post("/speak")
async def speak(body: SpeakIn):
    spoken = (body.text or "").strip()
    if not spoken:
        raise HTTPException(400, "Nothing to speak")
    try:
        path = await asyncio.to_thread(synthesize_wav, spoken)
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc
    data = path.read_bytes()
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    return Response(content=data, media_type="audio/wav")


@router.post("/command")
async def voice_command(body: VoiceIn):
    """Create a task from transcribed speech. The portal transcribes first, then calls this or /api/tasks."""
    prompt = (body.text or "").strip()
    if not prompt:
        raise HTTPException(400, "Speak a command or send text")
    task = await AGENT.create_task(prompt, body.autonomy, execution_mode=body.execution_mode)
    return {"id": task.id, "task_id": task.id, "status": task.status, "prompt": prompt}


@router.post("/command-audio")
async def voice_command_audio(
    audio: UploadFile = File(...),
    autonomy: str | None = Form(None),
    execution_mode: str | None = Form(None),
):
    prompt = await _transcribe_upload(audio)
    if not prompt.strip():
        raise HTTPException(400, "Whisper heard no speech")
    task = await AGENT.create_task(prompt, autonomy, execution_mode=execution_mode)
    return {"id": task.id, "task_id": task.id, "status": task.status, "prompt": prompt}


async def _transcribe_upload(audio: UploadFile) -> str:
    status = voice_status()["stt"]
    if not status.get("available"):
        raise HTTPException(503, status.get("reason") or "Whisper is unavailable")
    payload = await audio.read()
    if not payload:
        raise HTTPException(400, "Empty audio upload")
    if len(payload) > MAX_AUDIO:
        raise HTTPException(400, "Audio is larger than 8 MB")
    suffix = Path(audio.filename or "speech.wav").suffix or ".wav"
    handle = tempfile.NamedTemporaryFile(prefix="jarvis-stt-", suffix=suffix, delete=False)
    path = Path(handle.name)
    handle.write(payload)
    handle.close()
    settings = load_settings()
    model_name = getattr(getattr(settings, "voice", None), "stt_model", None) or "tiny.en"
    try:
        return await asyncio.to_thread(transcribe_wav, path, model_name)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(503, str(exc)) from exc
    finally:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
