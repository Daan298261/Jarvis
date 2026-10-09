"""Regressions from the development @ 35c8148 bughunt (items 1, 2, and 5)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from app.agent.front_responder import (
    SAFE_HELLO,
    apply_disposition,
    infer_arbitration_disposition,
    live_text_update,
    safe_hello,
    speakable_worker_remainder,
)
from app.agent.loop import AGENT
from app.agent.planning import CONVERSATION_CLASS
from app.config import AppSettings, SocialCommentarySettings
from app.events import BUS
from app.inference.front_runtime import FRONT_RUNTIME
from app.inference.manager import MANAGER
from app.persona.chat_delivery import (
    mark_stream_spoken,
    pending_chat_tts,
    publish_owner_text,
    reset_chat_delivery,
    stream_speak_offset,
    stream_spoken_prefix,
    tts_char_offset_for_reply,
)
from app.persona.owner_chat import reset_owner_conversations, stream_owner_chat
from app.persona.social import template_comment_for_intent
from app.persona.think_aloud import PROGRESS_TEMPLATE_LINES, progress_think_aloud_line

QUICK = "Your meeting is at 3 pm."
CONTINUATION = "Your meeting is at 3 pm. Actually, it moved to the board room."
REPLACEMENT = "Actually, the meeting moved to 4 pm tomorrow in room B."
CHOPPED = REPLACEMENT[len(QUICK) :]


def test_chopped_slice_is_the_reported_speech_bug():
    assert CHOPPED.startswith("ved to 4 pm")


def test_tts_offset_keeps_a_correction_that_starts_with_the_quick_answer():
    offset = tts_char_offset_for_reply(
        CONTINUATION,
        spoken_through=len(QUICK),
        spoken_prefix=QUICK,
    )
    assert offset == len(QUICK)
    remainder = speakable_worker_remainder(CONTINUATION, offset)
    assert remainder == "Actually, it moved to the board room."
    assert QUICK not in remainder


def test_tts_offset_speaks_a_replacement_in_full():
    offset = tts_char_offset_for_reply(
        REPLACEMENT,
        spoken_through=len(QUICK),
        spoken_prefix=QUICK,
    )
    assert offset == 0
    remainder = speakable_worker_remainder(REPLACEMENT, offset)
    assert remainder == REPLACEMENT
    assert remainder != CHOPPED.strip()


def test_tts_offset_without_a_stored_prefix_keeps_the_legacy_cursor():
    offset = tts_char_offset_for_reply(REPLACEMENT, spoken_through=len(QUICK), spoken_prefix="")
    assert offset == len(QUICK)


@pytest.mark.asyncio
async def test_publish_speaks_only_the_tail_when_the_reply_repeats_the_quick_answer(monkeypatch):
    monkeypatch.setattr("app.persona.chat_delivery.should_speak_chat_reply", lambda _settings: True)
    monkeypatch.setattr("app.persona.chat_delivery.BUS.publish_ephemeral", AsyncMock())
    monkeypatch.setattr("app.persona.chat_delivery.filter_text_for_speech", lambda text, **_kwargs: text)
    reset_chat_delivery()
    key = "bughunt:continuation"
    mark_stream_spoken(key, len(QUICK), prefix=QUICK)

    delivery = await publish_owner_text(
        CONTINUATION,
        source="owner_chat",
        speak=True,
        user_prompt="When is my meeting?",
        tts_char_offset=stream_speak_offset(key),
        spoken_prefix=stream_spoken_prefix(key),
    )
    assert delivery["spoken"] is True
    spoken = pending_chat_tts()[-1]["text"]
    assert spoken == "Actually, it moved to the board room."
    assert QUICK not in spoken
    reset_chat_delivery()


@pytest.mark.asyncio
async def test_publish_speaks_a_replacing_correction_in_full(monkeypatch):
    monkeypatch.setattr("app.persona.chat_delivery.should_speak_chat_reply", lambda _settings: True)
    monkeypatch.setattr("app.persona.chat_delivery.BUS.publish_ephemeral", AsyncMock())
    monkeypatch.setattr("app.persona.chat_delivery.filter_text_for_speech", lambda text, **_kwargs: text)
    reset_chat_delivery()
    key = "bughunt:replacement"
    mark_stream_spoken(key, len(QUICK), prefix=QUICK)

    delivery = await publish_owner_text(
        REPLACEMENT,
        source="owner_chat",
        speak=True,
        user_prompt="When is my meeting?",
        tts_char_offset=stream_speak_offset(key),
        spoken_prefix=stream_spoken_prefix(key),
    )
    assert delivery["spoken"] is True
    spoken = pending_chat_tts()[-1]["text"]
    assert spoken == REPLACEMENT
    assert not spoken.startswith("ved to")
    assert spoken != CHOPPED.strip()
    reset_chat_delivery()


def test_live_text_update_appends_a_continuation_and_replaces_a_correction():
    assert live_text_update(QUICK, CONTINUATION) == ("append", "Actually, it moved to the board room.")
    assert live_text_update(QUICK, REPLACEMENT) == ("replace", REPLACEMENT)
    assert live_text_update("", REPLACEMENT) == ("append", REPLACEMENT)
    assert live_text_update(QUICK, QUICK) is None
    assert apply_disposition(infer_arbitration_disposition(QUICK, REPLACEMENT), QUICK, REPLACEMENT) == REPLACEMENT


@pytest.mark.asyncio
async def test_owner_chat_emits_replace_previous_text_for_a_correction(jarvis_env, monkeypatch):
    del jarvis_env
    monkeypatch.setattr("app.agent.front_responder.ACK_HOLD_SECONDS", 0.05)
    reset_chat_delivery()

    class FrontProvider:
        model = "Qwen3.5-2B"

        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield QUICK

    async def worker_chat_stream(*_args, **_kwargs):
        await asyncio.sleep(0.25)
        yield REPLACEMENT

    async def no_weather(_text: str):
        return None

    async def no_hydrate(_conversation_id: str):
        return []

    async def instant_working_set(*_args, **_kwargs):
        from app.agent.turn_working_set import TurnWorkingSet

        return TurnWorkingSet(user_message="meeting", task_class="conversation")

    FRONT_RUNTIME.mark_for_tests(distinct=True, provider=FrontProvider())
    MANAGER.state.loaded = True
    MANAGER.provider = FrontProvider()
    monkeypatch.setattr(MANAGER, "chat_stream", worker_chat_stream)
    monkeypatch.setattr("app.agent.turn_working_set.compose_turn_working_set", instant_working_set)
    monkeypatch.setattr("app.persona.owner_chat.weather_system_message", no_weather)
    monkeypatch.setattr("app.persona.owner_chat.hydrate_conversation", no_hydrate)
    reset_owner_conversations()

    try:
        events = []
        async for event in stream_owner_chat("When is my meeting tomorrow?"):
            events.append(event)
    finally:
        FRONT_RUNTIME.reset_for_tests()
        reset_chat_delivery()

    replaces = [event for event in events if event.get("type") == "replace_previous_text"]
    assert len(replaces) == 1
    assert replaces[0]["text"] == REPLACEMENT
    assert replaces[0]["lane"] == "worker"
    deltas = [event.get("text") or "" for event in events if event.get("type") == "delta"]
    assert any(QUICK in text for text in deltas)
    assert REPLACEMENT not in deltas
    assert not any(text.startswith("ved to") for text in deltas)
    done = events[-1]
    assert done["type"] == "done"
    assert done["text"] == REPLACEMENT


@pytest.mark.asyncio
async def test_conversation_loop_publishes_replace_and_speaks_the_full_correction(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.agent.front_responder.ACK_HOLD_SECONDS", 0.05)
    reset_chat_delivery()
    published: list[dict] = []
    original = BUS.publish

    async def capture(task_id, kind, title, detail="", stage="", **kwargs):
        published.append(
            {
                "task_id": task_id,
                "kind": kind,
                "detail": detail,
                "persist": kwargs.get("persist", True),
            }
        )
        return await original(task_id, kind, title, detail, stage, **kwargs)

    monkeypatch.setattr(BUS, "publish", capture)

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del kwargs
            joined = "\n".join(getattr(item, "content", "") or "" for item in (messages or []))
            if "front_responder" in joined.lower():
                yield QUICK
                return
            await asyncio.sleep(0.3)
            yield REPLACEMENT

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            return ChatResult(content="unexpected")

    async def no_weather(_text: str):
        return None

    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True
    MANAGER.state.context_size = 16384
    monkeypatch.setattr("app.agent.loop.weather_system_message", no_weather)

    FRONT_RUNTIME.reset_for_tests()
    task = await AGENT.create_task("When is my meeting tomorrow?")
    assert task.task_class == CONVERSATION_CLASS
    runner = AGENT._tasks.get(task.id)
    if runner:
        await runner

    replaces = [item for item in published if item["kind"] == "replace_previous_text" and item["task_id"] == task.id]
    assert len(replaces) == 1
    assert replaces[0]["detail"] == REPLACEMENT
    assert replaces[0]["persist"] is False
    assert not any(
        item["kind"] == "assistant_delta" and REPLACEMENT in (item["detail"] or "")
        for item in published
        if item["task_id"] == task.id
    )


@pytest.mark.asyncio
async def test_conversation_loop_speaks_the_replacing_correction_in_full(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.agent.front_responder.ACK_HOLD_SECONDS", 0.05)
    monkeypatch.setattr("app.persona.chat_delivery.filter_text_for_speech", lambda text, **_kwargs: text)
    reset_chat_delivery()

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del kwargs
            joined = "\n".join(getattr(item, "content", "") or "" for item in (messages or []))
            if "front_responder" in joined.lower():
                yield QUICK
                return
            await asyncio.sleep(0.3)
            yield REPLACEMENT

    async def no_weather(_text: str):
        return None

    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True
    MANAGER.state.context_size = 16384
    monkeypatch.setattr("app.agent.loop.weather_system_message", no_weather)
    FRONT_RUNTIME.reset_for_tests()

    task = await AGENT.create_task("When is my meeting tomorrow?")
    runner = AGENT._tasks.get(task.id)
    if runner:
        await runner

    spoken = [item["text"] for item in pending_chat_tts()]
    full = [text for text in spoken if "room B" in text]
    assert full, spoken
    assert full[-1] == REPLACEMENT
    assert not any(text.startswith("ved to") for text in spoken)


def test_address_style_including_neutral_uses_one_vocative():
    neutral = AppSettings(social_commentary=SocialCommentarySettings(address_style="neutral"))
    sir = AppSettings(social_commentary=SocialCommentarySettings(address_style="sir_maam"))
    named = AppSettings(
        social_commentary=SocialCommentarySettings(
            address_style="configured",
            configured_address_name="Alex",
        )
    )
    assert SAFE_HELLO == "Hello."
    assert safe_hello(neutral) == "Hello."
    assert safe_hello(sir) == "Hello, sir."
    assert safe_hello(named) == "Hello, Alex."
    assert "sir" not in safe_hello(neutral).lower()

    hair = {
        "topic": "appearance.hair_state",
        "value": "dishevelled",
        "tone": "light",
        "address_style": "neutral",
    }
    neutral_line = template_comment_for_intent(hair)
    assert neutral_line is not None
    assert neutral_line.endswith(".")
    assert ", sir" not in neutral_line
    sir_line = template_comment_for_intent({**hair, "address_style": "sir_maam"})
    assert sir_line is not None and sir_line.endswith(", sir.")
    named_line = template_comment_for_intent(
        {**hair, "address_style": "first_name", "configured_address_name": "Dana"}
    )
    assert named_line is not None and ", Dana." in named_line


def test_progress_line_respects_neutral_and_sir(monkeypatch):
    neutral = AppSettings(social_commentary=SocialCommentarySettings(address_style="neutral"))
    sir = AppSettings(social_commentary=SocialCommentarySettings(address_style="sir_maam"))
    monkeypatch.setattr("app.tts.persona_speech.load_settings", lambda: neutral)
    plain = progress_think_aloud_line("model load")
    assert plain == PROGRESS_TEMPLATE_LINES[0]
    assert "sir" not in plain.lower()
    monkeypatch.setattr("app.tts.persona_speech.load_settings", lambda: sir)
    addressed = progress_think_aloud_line("model load")
    assert addressed == "Still on it, sir — the main model is waking up."
