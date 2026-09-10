from __future__ import annotations

import base64

import pytest
from fastapi import FastAPI, HTTPException
from starlette.testclient import TestClient

from app.mobile import identity, realtime_voice, store
from tests.test_mobile_companion import paired, signature


@pytest.fixture
def mobile_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def _reset_realtime(mobile_env):
    realtime_voice.reset_state()
    yield
    realtime_voice.reset_state()


def _headers():
    key, device = paired()
    session = identity.exchange(device["id"], signature(key, device))
    return device, {
        "Authorization": "Bearer " + session["access_token"],
        "X-Jarvis-Device": device["id"],
    }


def test_audio_sequence_rejects_replay_and_gaps(mobile_env):
    session = realtime_voice.create_session({"id": "phone"})
    turn = realtime_voice.begin_turn(session)
    realtime_voice.accept_audio(turn, 0, b"\0\0")
    with pytest.raises(HTTPException) as dup:
        realtime_voice.accept_audio(turn, 0, b"\1\1")
    assert dup.value.status_code == 409
    with pytest.raises(HTTPException) as gap:
        realtime_voice.accept_audio(turn, 2, b"\2\2")
    assert gap.value.status_code == 409


def test_byte_limit_and_interrupt_clear_memory(mobile_env):
    session = realtime_voice.create_session({"id": "phone"})
    turn = realtime_voice.begin_turn(session)
    chunk = b"\0" * 1024
    seq = 0
    while len(turn.audio) + len(chunk) <= realtime_voice.MAX_AUDIO_BYTES:
        realtime_voice.accept_audio(turn, seq, chunk)
        seq += 1
    with pytest.raises(HTTPException) as over:
        realtime_voice.accept_audio(turn, seq, chunk)
    assert over.value.status_code == 413
    realtime_voice.interrupt_turn(turn)
    assert turn.cancelled and len(turn.audio) == 0


def test_interrupt_cancels_active_agent_task(mobile_env, monkeypatch):
    session = realtime_voice.create_session({"id": "phone"})
    turn = realtime_voice.begin_turn(session)
    turn.active_task_id = "task-abc"
    cancelled: list[str] = []

    class _Agent:
        def cancel(self, task_id: str) -> None:
            cancelled.append(task_id)

    monkeypatch.setattr("app.agent.loop.AGENT", _Agent())
    realtime_voice.interrupt_turn(turn)
    assert cancelled == ["task-abc"]
    assert turn.active_task_id is None


def test_reconnect_resumes_same_device_session_only(mobile_env):
    first = realtime_voice.create_session({"id": "phone-a"})
    turn = realtime_voice.begin_turn(first)
    realtime_voice.accept_audio(turn, 0, b"\0\0")
    resumed = realtime_voice.get_session(first.session_id, "phone-a")
    assert resumed.current_turn_id == turn.turn_id
    assert resumed.turns[turn.turn_id].last_seq == 0
    with pytest.raises(HTTPException) as stolen:
        realtime_voice.get_session(first.session_id, "phone-b")
    assert stolen.value.status_code == 404


def test_rate_limit_blocks_excessive_turns(mobile_env):
    session = realtime_voice.create_session({"id": "phone"})
    for _ in range(realtime_voice.MAX_TURNS_PER_MINUTE):
        realtime_voice.begin_turn(session)
    with pytest.raises(HTTPException) as limited:
        realtime_voice.begin_turn(session)
    assert limited.value.status_code == 429


@pytest.mark.asyncio
async def test_stream_reply_emits_tts_before_final_and_uses_profile(mobile_env, monkeypatch):
    session = realtime_voice.create_session({"id": "phone"}, voice_profile_id="butler_original_v1")
    turn = realtime_voice.begin_turn(session)
    turn.finalized = True
    turn.transcript = "Hello"
    spoken = []

    async def submit(device_id, request_id, prompt, profile=None, conversation_id=None, attachments=None):
        return {"task_id": "t1", "conversation_id": "c1"}

    snapshots = iter([
        {"status": "running", "result": "One sentence."},
        {"status": "completed", "result": "One sentence. Two sentence."},
    ])

    async def snapshot(task_id):
        return next(snapshots)

    async def synthesize(text, *, voice_profile_id=None):
        spoken.append((text, voice_profile_id))
        return b"RIFFdata"

    monkeypatch.setattr(realtime_voice.service, "submit", submit)
    monkeypatch.setattr(realtime_voice.service, "task_snapshot", snapshot)
    monkeypatch.setattr(realtime_voice, "synthesize_speech", synthesize)

    events = [event async for event in realtime_voice.stream_reply(turn, "Hello")]
    assert events[0]["type"] == "tts" and events[0]["final"] is False and events[0]["data"]
    assert any(event["type"] == "tts" and event["final"] for event in events)
    assert any(event["type"] == "done" for event in events)
    assert spoken and all(profile == "butler_original_v1" for _, profile in spoken)
    assert spoken[0][0] == "One sentence."


def test_websocket_requires_device_auth_and_accepts_hello(mobile_env):
    from app.api.companion import router

    app = FastAPI()
    app.include_router(router)
    with TestClient(app) as client:
        with pytest.raises(Exception):
            with client.websocket_connect("/api/companion/voice/realtime"):
                pass
        _device, headers = _headers()
        with client.websocket_connect("/api/companion/voice/realtime", headers=headers) as ws:
            ws.send_json({"type": "hello", "voice_profile_id": "butler_original_v1"})
            opened = ws.receive_json()
            assert opened["type"] == "session"
            assert opened["session_id"]
            assert "token" not in opened
            assert opened["limits"]["format"] == "pcm16le"
            ws.send_json({"type": "start_turn"})
            turn = ws.receive_json()
            assert turn["type"] == "turn"
            payload = base64.b64encode(b"\0\0").decode()
            ws.send_json({"type": "audio", "turn_id": turn["turn_id"], "seq": 0, "data": payload})
            ws.send_json({"type": "audio", "turn_id": turn["turn_id"], "seq": 0, "data": payload})
            error = ws.receive_json()
            assert error["type"] == "error"
            assert "Replay" in error["detail"] or "duplicate" in error["detail"].lower()


@pytest.mark.asyncio
async def test_synthesize_speech_uses_profile_engine_and_speaker(monkeypatch):
    from app.workers import voice

    class _Tts:
        engine_id = "kokoro"
        engine_hint = "kokoro"
        speaker_ref = "bm_george"
        pack_path = ""

    class _Profile:
        tts = _Tts()

    class _Catalog:
        def get_available(self, profile_id: str):
            return _Profile() if profile_id == "butler_original_v1" else None

    routed: list[tuple[str, str, str]] = []

    async def fake_synth(text, *, engine_id, profile=None, speaker_ref="", model_dir=None):
        routed.append((text, engine_id, speaker_ref))
        return b"RIFFwav"

    monkeypatch.setattr("app.voice_profiles.catalog.get_catalog", lambda: _Catalog())
    monkeypatch.setattr(voice, "pick_engine_for_profile", lambda _p: "kokoro")
    monkeypatch.setattr(voice, "synthesize_with_engine", fake_synth)

    audio = await voice.synthesize_speech("Hello", voice_profile_id="butler_original_v1")
    assert audio == b"RIFFwav"
    assert routed == [("Hello", "kokoro", "bm_george")]


@pytest.mark.asyncio
async def test_clip_endpoints_remain_as_fallback(mobile_env, monkeypatch):
    from app.api.companion import router
    from app.workers import voice

    app = FastAPI()
    app.include_router(router)
    _device, headers = _headers()

    async def synthesize(text, *, voice_profile_id=None):
        return b"RIFFclip"

    monkeypatch.setattr(voice, "synthesize_speech", synthesize)
    import httpx
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/api/companion/voice/speak",
            headers=headers,
            json={"text": "Fallback clip", "voice_profile_id": "butler_original_v1"},
        )
    assert response.status_code == 200 and response.content == b"RIFFclip"
