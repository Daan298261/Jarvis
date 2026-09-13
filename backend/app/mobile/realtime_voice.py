"""Authenticated duplex voice sessions for the Android companion (RFC-0064).

Audio stays memory-only. Turns use unpredictable IDs, monotonic sequences,
per-device rate limits, and replay rejection. HTTPS clip STT/TTS remain the
fallback; this module streams partial transcripts and sentence-level TTS.
"""
from __future__ import annotations

import asyncio
import base64
import binascii
import io
import re
import secrets
import time
import wave
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, AsyncIterator, Callable, Awaitable

from fastapi import HTTPException, WebSocket, WebSocketDisconnect

from . import service
from .store import database, get
from ..workers.voice import synthesize_speech, transcribe_audio, VoiceSTTError

MAX_AUDIO_BYTES = 4 * 1024 * 1024
MAX_TURN_SECONDS = 90
MAX_TURNS_PER_MINUTE = 12
MAX_SESSIONS_PER_DEVICE = 2
SESSION_TTL_SECONDS = 120
CHUNK_PCM_RATE = 16000
SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")


@dataclass
class VoiceTurn:
    turn_id: str
    device_id: str
    conversation_id: str | None
    voice_profile_id: str | None
    inference_profile: str | None = None
    started_at: float = field(default_factory=time.monotonic)
    audio: bytearray = field(default_factory=bytearray)
    last_seq: int = -1
    seen_seqs: set[int] = field(default_factory=set)
    cancelled: bool = False
    finalized: bool = False
    transcript: str = ""
    tts_seq: int = 0
    active_task_id: str | None = None


@dataclass
class VoiceSession:
    session_id: str
    device_id: str
    conversation_id: str | None = None
    voice_profile_id: str | None = None
    inference_profile: str | None = None
    created_at: float = field(default_factory=time.monotonic)
    turns: dict[str, VoiceTurn] = field(default_factory=dict)
    current_turn_id: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


_SESSIONS: dict[str, VoiceSession] = {}
_DEVICE_SESSIONS: dict[str, set[str]] = defaultdict(set)
_RATE_WINDOWS: dict[str, deque[float]] = defaultdict(deque)
_SEND: dict[str, Callable[[dict[str, Any]], Awaitable[None]]] = {}


def _purge_expired() -> None:
    now = time.monotonic()
    expired = [sid for sid, session in _SESSIONS.items() if now - session.created_at > SESSION_TTL_SECONDS]
    for sid in expired:
        _drop_session(sid)


def _drop_session(session_id: str) -> None:
    session = _SESSIONS.pop(session_id, None)
    _SEND.pop(session_id, None)
    if not session:
        return
    _DEVICE_SESSIONS[session.device_id].discard(session_id)
    if not _DEVICE_SESSIONS[session.device_id]:
        _DEVICE_SESSIONS.pop(session.device_id, None)


def _rate_ok(device_id: str) -> bool:
    window = _RATE_WINDOWS[device_id]
    now = time.monotonic()
    while window and window[0] < now - 60:
        window.popleft()
    if len(window) >= MAX_TURNS_PER_MINUTE:
        return False
    window.append(now)
    return True


def create_session(
    device: dict,
    conversation_id: str | None = None,
    voice_profile_id: str | None = None,
    inference_profile: str | None = None,
) -> VoiceSession:
    _purge_expired()
    device_id = device["id"]
    active = _DEVICE_SESSIONS[device_id]
    while len(active) >= MAX_SESSIONS_PER_DEVICE:
        oldest = min(active, key=lambda sid: _SESSIONS[sid].created_at)
        _drop_session(oldest)
    session = VoiceSession(
        session_id=secrets.token_urlsafe(24),
        device_id=device_id,
        conversation_id=conversation_id,
        voice_profile_id=voice_profile_id,
        inference_profile=inference_profile,
    )
    _SESSIONS[session.session_id] = session
    active.add(session.session_id)
    return session


def get_session(session_id: str, device_id: str) -> VoiceSession:
    _purge_expired()
    session = _SESSIONS.get(session_id)
    if not session or session.device_id != device_id:
        raise HTTPException(404, "Voice session not found")
    session.created_at = time.monotonic()
    return session


def begin_turn(session: VoiceSession, turn_id: str | None = None) -> VoiceTurn:
    if not _rate_ok(session.device_id):
        raise HTTPException(429, "Voice turn rate limit exceeded; wait before speaking again")
    tid = turn_id or secrets.token_urlsafe(18)
    if tid in session.turns:
        raise HTTPException(409, "Turn already exists")
    turn = VoiceTurn(
        turn_id=tid,
        device_id=session.device_id,
        conversation_id=session.conversation_id,
        voice_profile_id=session.voice_profile_id,
        inference_profile=session.inference_profile,
    )
    session.turns[tid] = turn
    session.current_turn_id = tid
    return turn


def accept_audio(turn: VoiceTurn, seq: int, payload: bytes) -> None:
    if turn.cancelled or turn.finalized:
        raise HTTPException(409, "Turn is closed")
    if time.monotonic() - turn.started_at > MAX_TURN_SECONDS:
        raise HTTPException(408, "Voice turn exceeded duration limit")
    if seq < 0 or seq in turn.seen_seqs:
        raise HTTPException(409, "Replay or duplicate audio sequence rejected")
    if seq != turn.last_seq + 1:
        raise HTTPException(409, "Out-of-order audio sequence rejected")
    if len(payload) == 0:
        raise HTTPException(400, "Empty audio frame")
    if len(turn.audio) + len(payload) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Voice turn exceeds byte limit")
    turn.seen_seqs.add(seq)
    turn.last_seq = seq
    turn.audio.extend(payload)


def interrupt_turn(turn: VoiceTurn) -> None:
    turn.cancelled = True
    turn.audio.clear()
    task_id = turn.active_task_id
    if task_id:
        try:
            from ..agent.loop import AGENT

            AGENT.cancel(task_id)
        except Exception:
            pass
        turn.active_task_id = None


def _pcm_to_wav(pcm: bytes, sample_rate: int = CHUNK_PCM_RATE) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm)
    return buffer.getvalue()


def _split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in SENTENCE_SPLIT.split(text.strip()) if part.strip()]
    return parts or ([text.strip()] if text.strip() else [])


async def partial_transcript(turn: VoiceTurn) -> str:
    if turn.cancelled or len(turn.audio) < CHUNK_PCM_RATE:
        return turn.transcript
    try:
        text = (await transcribe_audio(_pcm_to_wav(bytes(turn.audio)), "partial.wav")).strip()
    except (VoiceSTTError, RuntimeError):
        return turn.transcript
    if text:
        turn.transcript = text
    return turn.transcript


async def finalize_transcript(turn: VoiceTurn) -> str:
    if turn.cancelled:
        return ""
    if turn.finalized and turn.transcript:
        return turn.transcript
    if not turn.audio:
        raise HTTPException(400, "No audio received for this turn")
    try:
        text = (await transcribe_audio(_pcm_to_wav(bytes(turn.audio)), "turn.wav")).strip()
    except VoiceSTTError as exc:
        raise HTTPException(503, str(exc)) from exc
    turn.audio.clear()
    turn.finalized = True
    turn.transcript = text
    return text


async def stream_reply(turn: VoiceTurn, text: str) -> AsyncIterator[dict[str, Any]]:
    """Submit the user utterance and stream sentence-level TTS as the reply grows."""
    if turn.cancelled:
        return
    request_id = secrets.token_urlsafe(16)
    try:
        result = await service.submit(
            turn.device_id,
            request_id,
            text,
            profile=turn.inference_profile,
            conversation_id=turn.conversation_id,
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(503, str(getattr(exc, "detail", exc))[:200]) from exc
    turn.conversation_id = result.get("conversation_id") or turn.conversation_id
    turn.active_task_id = result.get("task_id")
    spoken = ""
    while not turn.cancelled:
        snapshot = await service.task_snapshot(result["task_id"])
        response = str(snapshot.get("result") or "")
        if response.startswith(spoken) and len(response) > len(spoken):
            remainder = response[len(spoken):]
            terminal = snapshot["status"] in service.TERMINAL
            ready = terminal or remainder.endswith((".", "!", "?", "\n"))
            if ready and remainder.strip():
                for sentence in _split_sentences(remainder):
                    if turn.cancelled:
                        return
                    audio = await synthesize_speech(sentence, voice_profile_id=turn.voice_profile_id)
                    turn.tts_seq += 1
                    yield {
                        "type": "tts",
                        "turn_id": turn.turn_id,
                        "seq": turn.tts_seq,
                        "format": "wav",
                        "data": base64.b64encode(audio).decode(),
                        "text": sentence,
                        "final": False,
                    }
                spoken = response
        if snapshot["status"] in service.TERMINAL:
            turn.tts_seq += 1
            yield {
                "type": "tts",
                "turn_id": turn.turn_id,
                "seq": turn.tts_seq,
                "format": "wav",
                "data": "",
                "text": spoken,
                "final": True,
            }
            yield {
                "type": "done",
                "turn_id": turn.turn_id,
                "conversation_id": turn.conversation_id,
                "task_id": result.get("task_id"),
                "text": spoken,
            }
            return
        await asyncio.sleep(0.25)


async def handle_realtime(websocket: WebSocket, device: dict) -> None:
    """JSON WebSocket protocol for duplex companion voice."""
    await websocket.accept()
    session: VoiceSession | None = None

    async def send(payload: dict[str, Any]) -> None:
        await websocket.send_json(payload)

    try:
        while True:
            message = await websocket.receive_json()
            kind = message.get("type")
            if kind == "hello":
                if session is not None:
                    await send({"type": "error", "detail": "Session already open"})
                    continue
                conversation_id = message.get("conversation_id")
                voice_profile_id = message.get("voice_profile_id")
                inference_profile = message.get("profile") or message.get("inference_profile")
                session = create_session(device, conversation_id, voice_profile_id, inference_profile)
                _SEND[session.session_id] = send
                await send({
                    "type": "session",
                    "session_id": session.session_id,
                    "device_id": device["id"],
                    "limits": {
                        "max_audio_bytes": MAX_AUDIO_BYTES,
                        "max_turn_seconds": MAX_TURN_SECONDS,
                        "sample_rate": CHUNK_PCM_RATE,
                        "format": "pcm16le",
                    },
                })
                continue

            if kind == "reconnect":
                session_id = str(message.get("session_id") or "")
                try:
                    session = get_session(session_id, device["id"])
                except HTTPException as exc:
                    await send({"type": "error", "detail": str(exc.detail)})
                    continue
                _SEND[session.session_id] = send
                turn_id = message.get("turn_id") or session.current_turn_id
                turn = session.turns.get(turn_id) if turn_id else None
                await send({
                    "type": "session",
                    "session_id": session.session_id,
                    "resumed_turn_id": turn.turn_id if turn and not turn.cancelled else None,
                    "last_seq": turn.last_seq if turn else -1,
                    "device_id": device["id"],
                })
                continue

            if session is None:
                await send({"type": "error", "detail": "Send hello or reconnect first"})
                continue

            with database() as db:
                live = get(db, "device", device["id"])
            if not live or live["status"] != "active":
                await send({"type": "error", "detail": "Device revoked"})
                await websocket.close(code=1008)
                return

            if kind == "start_turn":
                try:
                    turn = begin_turn(session, message.get("turn_id"))
                except HTTPException as exc:
                    await send({"type": "error", "detail": str(exc.detail)})
                    continue
                await send({"type": "turn", "turn_id": turn.turn_id, "seq_start": 0})
                continue

            if kind == "close":
                break

            turn_id = str(message.get("turn_id") or session.current_turn_id or "")
            turn = session.turns.get(turn_id)
            if not turn:
                await send({"type": "error", "detail": "Unknown turn"})
                continue

            if kind == "audio":
                seq = int(message.get("seq", -1))
                try:
                    raw = base64.b64decode(message.get("data") or "", validate=True)
                    accept_audio(turn, seq, raw)
                except HTTPException as exc:
                    await send({"type": "error", "detail": str(exc.detail)})
                    continue
                except (ValueError, binascii.Error):
                    await send({"type": "error", "detail": "Invalid audio payload"})
                    continue
                if turn.last_seq > 0 and turn.last_seq % 16 == 0:
                    partial = await partial_transcript(turn)
                    if partial:
                        await send({"type": "partial", "turn_id": turn.turn_id, "text": partial, "seq": turn.last_seq})
                continue

            if kind == "end_turn":
                try:
                    text = await finalize_transcript(turn)
                except HTTPException as exc:
                    await send({"type": "error", "detail": str(exc.detail)})
                    continue
                await send({"type": "final", "turn_id": turn.turn_id, "text": text})
                if not text:
                    await send({"type": "done", "turn_id": turn.turn_id, "text": ""})
                    continue
                try:
                    async for event in stream_reply(turn, text):
                        if turn.cancelled:
                            break
                        await send(event)
                except HTTPException as exc:
                    await send({"type": "error", "detail": str(exc.detail)})
                continue

            if kind == "interrupt":
                interrupt_turn(turn)
                await send({"type": "interrupted", "turn_id": turn.turn_id})
                continue

            await send({"type": "error", "detail": f"Unknown message type: {kind}"})
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await send({"type": "error", "detail": str(exc)[:200]})
        except Exception:
            pass
    finally:
        if session is not None:
            _drop_session(session.session_id)


# Test helpers
def reset_state() -> None:
    _SESSIONS.clear()
    _DEVICE_SESSIONS.clear()
    _RATE_WINDOWS.clear()
    _SEND.clear()
