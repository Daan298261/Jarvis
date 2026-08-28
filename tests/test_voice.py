from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.compaction import WORKING_STATE_MARKER, compact_history
from app.agent.planning import WorkingState
from app.inference.backends import normalize_chat_messages
from app.providers.base import ChatMessage


def _voice_worker():
    from app.api.voice import get_voice_status  # noqa: F401 - prime import graph

    import app.workers.voice as voice_worker

    return voice_worker


def test_normalize_chat_messages_merges_system_blocks_to_front():
    working = WorkingState(goal="write report", task_class="filesystem")
    compacted = compact_history(
        [
            ChatMessage(role="system", content="You are Jarvis."),
            ChatMessage(role="user", content="Do the thing."),
            ChatMessage(role="assistant", content="Working on it."),
        ],
        keep_last=2,
        working_state_block=working.as_prompt_block(),
    )
    roles_before = [message.role for message in compacted]
    assert roles_before.index("user") < roles_before.index("system", 1)

    normalized = normalize_chat_messages(compacted)
    assert normalized[0].role == "system"
    assert all(message.role != "system" for message in normalized[1:])
    assert WORKING_STATE_MARKER in normalized[0].content
    assert "You are Jarvis." in normalized[0].content


def test_normalize_chat_messages_preserves_non_system_order():
    messages = [
        ChatMessage(role="system", content="sys"),
        ChatMessage(role="user", content="u1"),
        ChatMessage(role="assistant", content="a1"),
        ChatMessage(role="tool", name="filesystem", tool_call_id="c1", content="ok"),
    ]
    normalized = normalize_chat_messages(messages)
    assert [message.role for message in normalized] == ["system", "user", "assistant", "tool"]


def test_voice_status_includes_install_hint(monkeypatch):
    voice_worker = _voice_worker()

    monkeypatch.setattr(voice_worker, "stt_backend", lambda: "faster-whisper")
    monkeypatch.setattr(voice_worker, "tts_backend", lambda: "sapi")
    monkeypatch.setattr(voice_worker, "local_whisper_model", lambda: None)
    status = voice_worker.voice_status()
    assert status["stt_ready"] is True
    assert "faster-whisper" in status["install_hint"]


def test_voice_status_windows_sapi_ready(monkeypatch):
    voice_worker = _voice_worker()

    monkeypatch.setattr(voice_worker, "stt_backend", lambda: "windows-sapi")
    monkeypatch.setattr(voice_worker, "tts_backend", lambda: "sapi")
    monkeypatch.setattr(voice_worker, "local_whisper_model", lambda: None)
    monkeypatch.setattr(voice_worker, "_find_ffmpeg", lambda: "/usr/bin/ffmpeg")
    status = voice_worker.voice_status()
    assert status["stt"] == "windows-sapi"
    assert status["stt_ready"] is True
    assert status["ffmpeg_available"] is True


def test_stt_backend_falls_back_to_windows_sapi_without_whisper_model(monkeypatch, tmp_path):
    voice_worker = _voice_worker()

    def module_available(name: str) -> bool:
        return name == "faster_whisper"

    monkeypatch.setattr(voice_worker, "local_whisper_model", lambda: None)
    monkeypatch.setattr(voice_worker, "_module_available", module_available)
    monkeypatch.setattr(voice_worker.sys, "platform", "win32")
    assert voice_worker.stt_backend() == "windows-sapi"

    model = tmp_path / "ggml-base.bin"
    model.write_bytes(b"fake")
    monkeypatch.setattr(voice_worker, "local_whisper_model", lambda: model)
    assert voice_worker.stt_backend() == "faster-whisper"

    monkeypatch.setattr(voice_worker, "local_whisper_model", lambda: None)
    monkeypatch.setattr(voice_worker.sys, "platform", "linux")
    assert voice_worker.stt_backend() == "faster-whisper"


def test_temp_path_closes_mkstemp_fd(monkeypatch):
    voice_worker = _voice_worker()

    closed: list[int] = []

    def fake_mkstemp(suffix: str = ".wav"):
        return 7, "/tmp/jarvis-voice-test.wav"

    monkeypatch.setattr(voice_worker.tempfile, "mkstemp", fake_mkstemp)
    monkeypatch.setattr(voice_worker.os, "close", lambda fd: closed.append(fd))

    path = voice_worker._temp_path(".wav")
    assert path == Path("/tmp/jarvis-voice-test.wav")
    assert closed == [7]


@pytest.mark.asyncio
async def test_transcribe_audio_reports_missing_stt(monkeypatch):
    voice_worker = _voice_worker()

    monkeypatch.setattr(
        voice_worker,
        "voice_status",
        lambda: {
            "stt_ready": False,
            "detail": "STT missing",
            "install_hint": "pip install faster-whisper",
        },
    )
    with pytest.raises(voice_worker.VoiceSTTError) as exc:
        await voice_worker.transcribe_audio(b"abc", "audio.webm")
    assert exc.value.code == "stt_unavailable"
    assert "faster-whisper" in exc.value.install_hint


@pytest.mark.asyncio
async def test_voice_listen_returns_structured_stt_error(jarvis_env, monkeypatch):
    from io import BytesIO

    from fastapi import UploadFile

    from app.api.voice import voice_listen
    from app.workers.voice import VoiceSTTError

    async def fake_transcribe(data: bytes, filename: str = "audio.webm") -> str:
        raise VoiceSTTError(
            "Windows speech recognition did not detect any speech.",
            code="stt_empty",
            install_hint="Speak clearly and retry.",
        )

    monkeypatch.setattr("app.api.voice.transcribe_audio", fake_transcribe)
    upload = UploadFile(filename="c.webm", file=BytesIO(b"fake-audio"))
    response = await voice_listen(audio=upload, autonomy=None)
    assert response.status_code == 503
    body = response.body.decode("utf-8")
    assert "stt_empty" in body
    assert "install_hint" in body


@pytest.mark.asyncio
async def test_voice_listen_reports_missing_stt(jarvis_env, monkeypatch):
    from io import BytesIO

    from fastapi import UploadFile

    from app.api.voice import voice_listen
    from app.workers.voice import VoiceSTTError

    async def fake_transcribe(data: bytes, filename: str = "audio.webm") -> str:
        raise VoiceSTTError(
            "STT missing",
            code="stt_unavailable",
            install_hint="pip install faster-whisper",
        )

    monkeypatch.setattr("app.api.voice.transcribe_audio", fake_transcribe)
    upload = UploadFile(filename="c.webm", file=BytesIO(b"fake-audio"))
    response = await voice_listen(audio=upload, autonomy=None)
    assert response.status_code == 503
    assert "stt_unavailable" in response.body.decode("utf-8")
