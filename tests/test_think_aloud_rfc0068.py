from __future__ import annotations

import asyncio

import pytest

from app.config import AppSettings, TtsSettings
from app.persona.chat_delivery import pending_chat_tts, reset_chat_delivery
from app.persona.quiet import should_speak_chat_reply
from app.persona.think_aloud import (
    THINK_ALOUD_COOLDOWN_SECONDS,
    THINK_ALOUD_DELAY_SECONDS,
    maybe_emit_think_aloud,
    reset_think_aloud_state,
    run_with_think_aloud,
    think_aloud_allowed,
)
from app.providers.base import ChatResult


@pytest.fixture(autouse=True)
def _clean_think_aloud():
    reset_think_aloud_state()
    reset_chat_delivery()
    yield
    reset_think_aloud_state()
    reset_chat_delivery()


@pytest.mark.asyncio
async def test_short_operation_does_not_think_aloud(monkeypatch):
    monkeypatch.setattr("app.persona.think_aloud.THINK_ALOUD_DELAY_SECONDS", 0.2)
    emitted = []

    async def fake_emit(task_id: str, *, context: str):
        emitted.append((task_id, context))
        return {"spoken": True}

    monkeypatch.setattr("app.persona.think_aloud.maybe_emit_think_aloud", fake_emit)

    async def fast():
        await asyncio.sleep(0.01)
        return "ok"

    out = await run_with_think_aloud("task-1", context="slow model", operation=fast, delay_seconds=0.2)
    assert out == "ok"
    assert emitted == []


@pytest.mark.asyncio
async def test_long_operation_fires_once_per_job(monkeypatch):
    monkeypatch.setattr("app.persona.think_aloud.THINK_ALOUD_DELAY_SECONDS", 0.05)
    calls = []

    async def fake_emit(task_id: str, *, context: str):
        from app.persona.think_aloud import _mark_spoken

        _mark_spoken(task_id)
        calls.append(task_id)
        return {"text": "One moment, sir.", "spoken": True}

    monkeypatch.setattr("app.persona.think_aloud.maybe_emit_think_aloud", fake_emit)

    async def slow():
        await asyncio.sleep(0.15)
        return 1

    await run_with_think_aloud("job-a", context="first", operation=slow, delay_seconds=0.05)
    await run_with_think_aloud("job-a", context="second", operation=slow, delay_seconds=0.05)
    assert calls == ["job-a"]


@pytest.mark.asyncio
async def test_cooldown_blocks_second_job(monkeypatch):
    monkeypatch.setattr("app.persona.think_aloud.THINK_ALOUD_DELAY_SECONDS", 0.02)
    monkeypatch.setattr("app.persona.think_aloud.THINK_ALOUD_COOLDOWN_SECONDS", 60.0)

    async def fake_emit(task_id: str, *, context: str):
        from app.persona.think_aloud import _mark_spoken

        _mark_spoken(task_id)
        return {"spoken": True}

    monkeypatch.setattr("app.persona.think_aloud.maybe_emit_think_aloud", fake_emit)

    async def slow():
        await asyncio.sleep(0.08)
        return None

    await run_with_think_aloud("job-1", context="x", operation=slow, delay_seconds=0.02)
    assert think_aloud_allowed("job-2") is False


@pytest.mark.asyncio
async def test_speak_chat_replies_off_suppresses(monkeypatch):
    settings = AppSettings(tts=TtsSettings(speak_chat_replies=False))
    monkeypatch.setattr("app.persona.think_aloud.load_settings", lambda: settings)
    assert think_aloud_allowed("t1", settings) is False

    monkeypatch.setattr("app.persona.think_aloud.THINK_ALOUD_DELAY_SECONDS", 0.02)

    async def slow():
        await asyncio.sleep(0.1)
        return None

    emitted = []

    async def track_emit(*args, **kwargs):
        emitted.append(1)
        return None

    monkeypatch.setattr("app.persona.think_aloud.maybe_emit_think_aloud", track_emit)
    await run_with_think_aloud("t1", context="x", operation=slow, delay_seconds=0.02)
    assert emitted == []


@pytest.mark.asyncio
async def test_quiet_or_dnd_suppresses(monkeypatch):
    settings = AppSettings(tts=TtsSettings(speak_chat_replies=True))
    monkeypatch.setattr("app.persona.think_aloud.load_settings", lambda: settings)
    monkeypatch.setattr("app.persona.quiet.is_quiet_or_dnd_active", lambda _s=None: True)
    assert should_speak_chat_reply(settings) is False
    assert think_aloud_allowed("t2", settings) is False


@pytest.mark.asyncio
async def test_maybe_emit_queues_tts(monkeypatch):
    from app.inference.manager import MANAGER

    class _Provider:
        async def chat(self, messages, **kwargs):
            return ChatResult(content="This may take a moment.")

    MANAGER.provider = _Provider()
    MANAGER.state.loaded = True

    settings = AppSettings(tts=TtsSettings(speak_chat_replies=True))
    monkeypatch.setattr("app.persona.think_aloud.load_settings", lambda: settings)

    delivery = await maybe_emit_think_aloud("task-x", context="Waiting on tools")
    assert delivery is not None
    assert delivery["spoken"] is True
    queued = pending_chat_tts()
    assert any(item["source"] == "think_aloud" for item in queued)
    assert think_aloud_allowed("task-x", settings) is False


def test_delay_constants_in_rfc_range():
    assert 2.0 <= THINK_ALOUD_DELAY_SECONDS <= 3.0
    assert THINK_ALOUD_COOLDOWN_SECONDS >= 30
