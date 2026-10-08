from __future__ import annotations

import time
import asyncio

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from ..agent.loop import AGENT
from ..config import load_settings
from ..persona.quiet import should_speak_chat_reply
from ..tts.engines import engine_availability
from ..tts.persona_speech import SpeechRefused, speak_text
from ..workers.voice import VoiceSTTError, transcribe_audio, voice_status

router = APIRouter(prefix="/api/voice", tags=["voice"])


class VoiceIn(BaseModel):
    text: str
    autonomy: str | None = None


class SpeakIn(BaseModel):
    text: str
    # Ignored for model speech. The server resolves the active persona voice.
    # Catalog preview stays on /api/voice-profiles/{id}/preview.
    voice_profile_id: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
        pattern=r"^[a-z0-9_]+$",
    )
    lane: str | None = Field(default=None, max_length=32)
    model: str | None = Field(default=None, max_length=120)


async def _stt_error_response(exc: VoiceSTTError) -> JSONResponse:
    status = exc.status or await asyncio.to_thread(voice_status)
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
    status = await asyncio.to_thread(voice_status)
    tts_backend = status.get("tts")
    runtime = status.get("tts_runtime") or {}
    status["engines"] = await asyncio.to_thread(engine_availability)
    status["stt_backend_preference"] = settings.voice.stt_backend
    status["voicestudio_url"] = settings.voice.voicestudio_url
    status["whisper_model"] = settings.voice.whisper_model or None
    status["tts"] = {
        "speak_chat_replies": settings.tts.speak_chat_replies,
        "voice_profile_id": settings.tts.voice_profile_id or None,
        "speak_allowed": should_speak_chat_reply(settings),
        "backend": tts_backend,
        **runtime,
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
        return await _stt_error_response(exc)
    except RuntimeError as exc:
        status = await asyncio.to_thread(voice_status)
        return await _stt_error_response(
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
        return await _stt_error_response(exc)
    except RuntimeError as exc:
        status = await asyncio.to_thread(voice_status)
        return await _stt_error_response(
            VoiceSTTError(str(exc), code="stt_failed", install_hint=status.get("install_hint") or "")
        )
    return {"transcript": transcript}


@router.post("/speak")
async def voice_speak(body: SpeakIn):
    started = time.perf_counter()
    from ..tts.speech_safe import speech_safe

    # Every caller is sanitized here: a raw task result or error must never be read aloud.
    text = speech_safe(body.text)
    if not text:
        return Response(status_code=204)
    try:
        result = await speak_text(
            text,
            lane=body.lane or "worker",
            model=body.model or "",
        )
    except SpeechRefused:
        return Response(status_code=204)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    duration_ms = (time.perf_counter() - started) * 1000
    return Response(
        content=result.audio,
        media_type="audio/wav",
        headers={
            "Server-Timing": f"tts;dur={duration_ms:.1f}",
            "X-Jarvis-TTS-Engine": result.engine_id,
            "X-Jarvis-Voice-Profile": result.profile_id,
        },
    )
