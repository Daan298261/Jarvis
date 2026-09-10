from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from app.agent.loop import AGENT
from app.agent.planning import CONVERSATION_CLASS, is_plain_conversation
from app.inference.manager import MANAGER
from app.persona.chat_delivery import OWNER_CHAT_CHANNEL, pending_chat_tts, reset_chat_delivery
from app.persona.greeting import build_launch_greeting_text, maybe_send_launch_greeting, should_send_greeting
from app.persona.owner_chat import complete_owner_chat, reset_owner_conversations
from app.persona.session_state import reset_owner_session_state
from app.providers.base import ChatMessage


class DeltaProvider:
    async def chat_stream(self, messages, **kwargs) -> AsyncIterator[str]:
        del messages, kwargs

        async def gen():
            yield "Hello, "
            yield "sir."

        return gen()

    async def chat(self, messages, **kwargs):
        del messages, kwargs
        from app.providers.base import ChatResult

        return ChatResult(content="Hello, sir.")


@pytest.fixture(autouse=True)
def reset_persona_state():
    reset_owner_session_state()
    reset_chat_delivery()
    reset_owner_conversations()
    yield
    reset_owner_session_state()
    reset_chat_delivery()
    reset_owner_conversations()


def test_build_launch_greeting_is_short_and_conversational():
    text = build_launch_greeting_text()
    assert "Good" in text
    assert "RFC" not in text
    assert len(text) < 220


@pytest.mark.asyncio
async def test_launch_greeting_idempotent(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    startup_id = "test-startup-abc"
    assert should_send_greeting(startup_id)
    first = await maybe_send_launch_greeting(startup_id)
    assert first is not None
    assert first["greeting"]
    assert first["spoken"] is True
    second = await maybe_send_launch_greeting(startup_id)
    assert second is None
    assert len(pending_chat_tts()) == 1


def test_is_plain_conversation_heuristic():
    assert is_plain_conversation("How are you today?")
    assert not is_plain_conversation("Organize these files on my desktop and delete duplicates")


@pytest.mark.asyncio
async def test_owner_chat_streams_without_confirmation(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del kwargs
            assert messages[0].role == "system"
            yield "Certainly."
            yield " One moment."

    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True

    from app.persona.owner_chat import stream_owner_chat

    events = []
    async for event in stream_owner_chat("Tell me a quick hello."):
        events.append(event)

    assert events[0]["type"] == "start"
    deltas = [e for e in events if e["type"] == "delta"]
    assert len(deltas) == 2
    done = events[-1]
    assert done["type"] == "done"
    assert done["text"] == "Certainly. One moment."
    assert pending_chat_tts()


@pytest.mark.asyncio
async def test_conversation_task_skips_tool_confirmation(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "All well here."

        async def chat(self, messages, **kwargs):
            del messages, kwargs
            from app.providers.base import ChatResult

            return ChatResult(content="unexpected")

    MANAGER.provider = StreamProvider()
    MANAGER.state.loaded = True
    MANAGER.state.context_size = 16384

    task = await AGENT.create_task("How are you this evening?")
    assert task.task_class == CONVERSATION_CLASS
    await asyncio.sleep(0.05)
    runner = AGENT._tasks.get(task.id)
    if runner:
        await runner

    from app.db.session import SessionLocal
    from app.db.models import Task

    async with SessionLocal() as session:
        row = await session.get(Task, task.id)
        assert row is not None
        assert row.status == "completed"
        assert row.waiting_for_confirmation is False
        assert "well" in (row.result or "").lower()

    deltas = [item for item in pending_chat_tts() if item["source"] in {"owner_chat", "task_chat"}]
    assert deltas
