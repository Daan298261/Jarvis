from __future__ import annotations

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel

from ..agent.loop import AGENT
from ..workers.voice import VoiceSTTError, synthesize_speech, transcribe_audio, voice_status

router = APIRouter(prefix="/api/voice", tags=["voice"])


class VoiceIn(BaseModel):
    text: str
    autonomy: str | None = None


class SpeakIn(BaseModel):
    text: str


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
    try:
        wav = await synthesize_speech(body.text)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(content=wav, media_type="audio/wav")
