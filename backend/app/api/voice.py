from __future__ import annotations

import time

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..agent.loop import AGENT
from ..config import load_settings
from ..persona.quiet import should_speak_chat_reply
from ..workers.voice import VoiceSTTError, synthesize_speech, transcribe_audio, voice_status

router = APIRouter(prefix="/api/voice", tags=["voice"])


class VoiceIn(BaseModel):
    text: str
    autonomy: str | None = None


class SpeakIn(BaseModel):
    text: str
    voice_profile_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9_]+$",
    )


def _stt_error_response(exc: VoiceSTTError) -> JSONResponse:
    status = exc.status or voice_status()
    return JSONResponse(
        status_code=503,
        content={
            "error": exc.code,
            "detail": str(exc),
            "install_hint": exc.install_hint or status.get("install_hint", ""),
            "voice_status": status,
        },
    )


@router.get("/status")
async def get_voice_status():
    settings = load_settings()
    status = voice_status()
    status["tts"] = {
        "speak_chat_replies": settings.tts.speak_chat_replies,
        "voice_profile_id": settings.tts.voice_profile_id or None,
        "speak_allowed": should_speak_chat_reply(settings),
    }
    return status


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
    except VoiceSTTError as exc:
        return _stt_error_response(exc)
    except RuntimeError as exc:
        status = voice_status()
        return _stt_error_response(
            VoiceSTTError(str(exc), code="stt_failed", install_hint=status.get("install_hint") or "")
        )
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
    except VoiceSTTError as exc:
        return _stt_error_response(exc)
    except RuntimeError as exc:
        status = voice_status()
        return _stt_error_response(
            VoiceSTTError(str(exc), code="stt_failed", install_hint=status.get("install_hint") or "")
        )
    return {"transcript": transcript}


@router.post("/speak")
async def voice_speak(body: SpeakIn):
    started = time.perf_counter()
    try:
        wav = await synthesize_speech(body.text, voice_profile_id=body.voice_profile_id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    duration_ms = (time.perf_counter() - started) * 1000
    return Response(
        content=wav,
        media_type="audio/wav",
        headers={"Server-Timing": f"tts;dur={duration_ms:.1f}"},
    )
