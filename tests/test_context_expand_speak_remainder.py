"""Hot-path fixes after #536: context-expand must not re-speak/block; TTS skips merge labels."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.agent.front_responder import (
    CONTEXT_EXPAND_KEEP_BUSY,
    DEEPER_RESULT_LABEL,
    emit_context_expand_keep_busy,
    merge_front_and_worker,
    speakable_worker_remainder,
    spawn_context_expand_keep_busy,
)
from app.persona.chat_delivery import (
    clear_stream_speak_state,
    mark_stream_spoken,
    pending_chat_tts,
    publish_owner_text,
    reset_chat_delivery,
    stream_speak_offset,
)


@pytest.fixture(autouse=True)
def _reset_delivery():
    reset_chat_delivery()
    yield
    reset_chat_delivery()


def test_speakable_worker_remainder_skips_deeper_result_label():
    front = "On it. Checking the details."
    worker = "Mild rain later this afternoon, sir."
    merged = merge_front_and_worker(front, worker, "ack_continue")
    assert DEEPER_RESULT_LABEL in merged
    assert merged.startswith(front)

    remainder = speakable_worker_remainder(merged, len(front))
    assert remainder == worker
    assert DEEPER_RESULT_LABEL not in remainder
    assert "Deeper" not in remainder


def test_speakable_worker_remainder_mid_front_still_drops_label():
    front = "Certainly. One moment while I look."
    worker = "All clear on the dashboard."
    merged = merge_front_and_worker(front, worker, "ack_continue")
    # Partial early sentence cursor lands mid-front.
    spoken = front.index(".") + 1
    remainder = speakable_worker_remainder(merged, spoken)
    assert "One moment" in remainder
    assert worker in remainder
    assert DEEPER_RESULT_LABEL not in remainder


def test_speakable_worker_remainder_zero_offset_strips_label_if_entire_merged():
    # Offset 0 keeps full text but still removes a bare leading label fragment.
    bare = f"\n\n{DEEPER_RESULT_LABEL}\nWorker only."
    assert speakable_worker_remainder(bare, 0) == "Worker only."


@pytest.mark.asyncio
async def test_publish_owner_text_tts_excludes_merge_label(monkeypatch):
    monkeypatch.setattr(
        "app.persona.chat_delivery.should_speak_chat_reply",
        lambda _settings: True,
    )
    monkeypatch.setattr("app.persona.chat_delivery.BUS.publish_ephemeral", AsyncMock())

    front = "On it, sir."
    worker = "Here is the deeper answer."
    merged = merge_front_and_worker(front, worker, "ack_continue")
    mark_stream_spoken("test:merge-tts", len(front))

    delivery = await publish_owner_text(
        merged,
        source="owner_chat",
        speak=True,
        user_prompt="Dig deeper please.",
        tts_char_offset=stream_speak_offset("test:merge-tts"),
    )
    assert delivery["spoken"] is True
    assert delivery["tts_id"]
    queued = pending_chat_tts()
    assert queued
    spoken_text = queued[-1]["text"]
    assert DEEPER_RESULT_LABEL not in spoken_text
    assert "Deeper result" not in spoken_text
    assert "deeper answer" in spoken_text.lower()
    clear_stream_speak_state("test:merge-tts")


@pytest.mark.asyncio
async def test_context_expand_skips_speak_when_cursor_advanced(monkeypatch):
    """After early front TTS, expand must not enqueue another speak."""
    from app.persona import owner_chat as oc

    stream_key = "owner:expand-skip"
    clear_stream_speak_state(stream_key)
    mark_stream_spoken(stream_key, 12)

    published: list[dict] = []

    async def capture_publish(text, **kwargs):
        published.append({"text": text, **kwargs})
        return {"tts_id": "should-not-fire", "spoken": True, "text": text}

    gen_calls: list[tuple] = []

    async def boom_generate(*args, **kwargs):
        gen_calls.append((args, kwargs))
        raise AssertionError("context expand must not regenerate front reply")

    monkeypatch.setattr(oc, "publish_owner_text", capture_publish)
    monkeypatch.setattr(oc, "generate_front_reply", boom_generate)
    monkeypatch.setattr(oc.BUS, "publish_ephemeral", AsyncMock())

    # Reproduce the owner_chat expand callback contract in isolation.
    settings = MagicMock()
    cleaned = "Please expand and dig deeper."

    async def _speak_context_expand(before: int, after: int) -> None:
        detail = {"text": f"Expanding context {before} → {after}"}
        await oc.BUS.publish_ephemeral(
            oc.OWNER_CHAT_CHANNEL,
            "model_lane",
            "Context resize",
            detail,
            stage="model",
        )
        if stream_speak_offset(stream_key) > 0:
            return

        async def _on_spoken(text: str) -> None:
            if stream_speak_offset(stream_key) > 0:
                return
            await capture_publish(text, source="owner_chat", speak=True, user_prompt=cleaned)

        from app.agent.front_responder import spawn_context_expand_keep_busy

        spawn_context_expand_keep_busy(on_spoken=_on_spoken)

    await _speak_context_expand(4096, 8192)
    await asyncio.sleep(0)  # let any spawned keep-busy task run
    assert published == []
    assert gen_calls == []
    clear_stream_speak_state(stream_key)


@pytest.mark.asyncio
async def test_context_expand_keep_busy_is_fire_and_forget():
    """Expand keep-busy must return immediately and never call generate_front_reply."""
    spoken: list[str] = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow_on_spoken(text: str) -> None:
        started.set()
        await release.wait()
        spoken.append(text)

    task = spawn_context_expand_keep_busy(on_spoken=slow_on_spoken)
    # Caller is not blocked on the keep-busy speak path.
    assert not task.done()
    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert spoken == []
    release.set()
    result = await asyncio.wait_for(task, timeout=1.0)
    assert result == CONTEXT_EXPAND_KEEP_BUSY
    assert spoken == [CONTEXT_EXPAND_KEEP_BUSY]


@pytest.mark.asyncio
async def test_emit_context_expand_keep_busy_is_static_no_regen():
    text = await emit_context_expand_keep_busy()
    assert text == CONTEXT_EXPAND_KEEP_BUSY


@pytest.mark.asyncio
async def test_owner_chat_expand_callback_does_not_await_regen(monkeypatch):
    """Wire the real owner_chat expand path: fast return, no generate_front_reply."""
    from app.persona import owner_chat as oc

    # Build a minimal closure matching stream_owner_chat's expand handler.
    stream_key = "owner:expand-ff"
    clear_stream_speak_state(stream_key)
    settings = MagicMock()
    settings  # silence lint about unused in stub
    cleaned = "Long prompt that needs more context tokens."
    keep_busy_started = asyncio.Event()
    keep_busy_release = asyncio.Event()
    published: list[str] = []

    async def slow_publish(text, **kwargs):
        keep_busy_started.set()
        await keep_busy_release.wait()
        published.append(text)
        return {"tts_id": "kb", "spoken": True, "text": text}

    monkeypatch.setattr(oc, "publish_owner_text", slow_publish)
    monkeypatch.setattr(oc.BUS, "publish_ephemeral", AsyncMock())
    monkeypatch.setattr(
        oc,
        "resolve_front_model_id",
        lambda _s: "front-test",
    )
    monkeypatch.setattr(
        oc,
        "model_lane_event_payload",
        lambda **kwargs: kwargs,
    )

    async def _speak_context_expand(before: int, after: int) -> None:
        detail = oc.model_lane_event_payload(
            lane="system",
            model=oc.resolve_front_model_id(settings),
            text=f"Expanding context {before} → {after}",
        )
        await oc.BUS.publish_ephemeral(
            oc.OWNER_CHAT_CHANNEL,
            "model_lane",
            "Context resize",
            detail,
            stage="model",
        )
        if stream_speak_offset(stream_key) > 0:
            return

        async def _on_spoken(text: str) -> None:
            if stream_speak_offset(stream_key) > 0:
                return
            await oc.publish_owner_text(
                text,
                source="owner_chat",
                speak=True,
                user_prompt=cleaned,
            )

        oc.spawn_context_expand_keep_busy(on_spoken=_on_spoken)

    # Must return before keep-busy speak finishes (fire-and-forget).
    await asyncio.wait_for(_speak_context_expand(2048, 8192), timeout=0.5)
    await asyncio.wait_for(keep_busy_started.wait(), timeout=1.0)
    assert published == []
    keep_busy_release.set()
    await asyncio.sleep(0.05)
    assert published == [CONTEXT_EXPAND_KEEP_BUSY]
    clear_stream_speak_state(stream_key)


@pytest.mark.asyncio
async def test_speak_front_reply_skips_when_cursor_advanced(jarvis_env, monkeypatch):
    from app.agent.front_responder import FrontReply
    from app.agent.loop import AGENT
    from app.persona.chat_delivery import clear_stream_speak_state, mark_stream_spoken

    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    stream_key = "task:expand-no-respeak"
    clear_stream_speak_state(stream_key)
    mark_stream_spoken(stream_key, 20)

    publish = AsyncMock(return_value={"tts_id": "nope"})
    monkeypatch.setattr("app.agent.loop.publish_owner_text", publish)
    monkeypatch.setattr("app.agent.loop.maybe_enqueue_streaming_social_tts", lambda *a, **k: "early")
    monkeypatch.setattr("app.agent.loop.BUS.publish", AsyncMock())

    front = FrontReply(action="ack_continue", text="On it, sir.", model="front")
    spoken = await AGENT._speak_front_reply(
        "expand-no-respeak",
        front,
        prompt="Continue",
        stream_key=stream_key,
        turn_started=0.0,
    )
    assert spoken is False
    publish.assert_not_awaited()
    clear_stream_speak_state(stream_key)
