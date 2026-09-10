import asyncio
from contextlib import nullcontext

import pytest

pytest.importorskip("aiortc")
from app.mobile import media


@pytest.mark.asyncio
async def test_interruption_during_tts_does_not_enqueue_old_audio(monkeypatch):
    started, release = asyncio.Event(), asyncio.Event()
    selected = []
    async def synthesize(text, **kwargs):
        selected.append(kwargs.get("voice_profile_id"))
        started.set()
        await release.wait()
        return b"not decoded after interruption"
    monkeypatch.setattr(media, "synthesize_speech", synthesize)
    speaker = media.Speaker()
    work = asyncio.create_task(speaker.speak("old answer", "butler_original_v1"))
    await started.wait()
    speaker.interrupt()
    release.set()
    await work
    assert selected == ["butler_original_v1"]
    assert speaker.queue.empty()
    speaker.stop()


def test_call_voice_uses_paired_device_profile(monkeypatch):
    monkeypatch.setattr(media, "database", lambda: nullcontext(object()))
    monkeypatch.setattr(
        media,
        "get",
        lambda db, kind, device_id: {"voice_profile_id": "butler_original_v1"},
    )
    bridge = media.VoiceBridge({"id": "call", "device_id": "phone"})
    assert bridge.voice_profile_id() == "butler_original_v1"
    bridge.stop()


@pytest.mark.asyncio
async def test_stop_is_transcribed_while_task_is_responding(monkeypatch):
    from app.agent.loop import AGENT
    bridge = media.VoiceBridge({"id": "call", "device_id": "phone", "task_id": "running-task"})
    blocked = asyncio.Event()
    bridge.turn = asyncio.create_task(blocked.wait())
    bridge.utterances.put_nowait("queued instruction")
    async def transcribe(*args):
        return "Stop!"
    cancelled = []
    monkeypatch.setattr(media, "transcribe_audio", transcribe)
    monkeypatch.setattr(AGENT, "cancel", cancelled.append)
    await bridge.accept_audio(bytes(320))
    assert cancelled == ["running-task"]
    assert bridge.utterances.empty()
    assert not bridge.turn.done()
    bridge.stop()
    await asyncio.gather(bridge.turn, return_exceptions=True)


@pytest.mark.asyncio
async def test_followup_speech_is_queued_while_answer_runs(monkeypatch):
    bridge = media.VoiceBridge({"id": "call", "device_id": "phone"})
    async def transcribe(*args):
        return "Also check tomorrow"
    monkeypatch.setattr(media, "transcribe_audio", transcribe)
    await bridge.accept_audio(bytes(320))
    assert bridge.utterances.get_nowait() == "Also check tomorrow"
    bridge.stop()
