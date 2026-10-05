"""Front lane must not wait on weather HTTP (owner chat + conversation loop)."""

from __future__ import annotations

import asyncio

import pytest

from app.agent.front_responder import FrontReply
from app.agent.loop import AGENT, CONVERSATION_CLASS
from app.agent.metrics import LiveTaskMetrics
from app.agent.planning import WorkingState
from app.db.models import Task
from app.db.session import SessionLocal
from app.inference.manager import MANAGER
from app.persona.owner_chat import stream_owner_chat


@pytest.mark.asyncio
async def test_owner_chat_front_before_weather_http(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    order: list[str] = []
    release_weather = asyncio.Event()

    # ack_continue forces the worker path so weather is awaited after front emit.
    prefetched = FrontReply(
        action="ack_continue",
        text="On it.",
        model="front",
        first_text_ms=2.0,
        complete_ms=2.0,
    )

    async def track_front(*_a, **_k):
        order.append("front")
        return prefetched

    async def slow_weather(prompt: str):
        del prompt
        order.append("weather_start")
        await release_weather.wait()
        order.append("weather_done")
        return None

    class StreamProvider:
        async def chat_stream(self, messages, **kwargs):
            del messages, kwargs
            yield "Certainly."

    async def track_load(settings, profile_name=None):
        order.append("load")
        MANAGER.provider = StreamProvider()
        MANAGER.state.loaded = True

    monkeypatch.setattr("app.persona.owner_chat.generate_front_reply", track_front)
    monkeypatch.setattr("app.persona.owner_chat.weather_system_message", slow_weather)
    monkeypatch.setattr("app.persona.owner_chat.MANAGER.load", track_load)
    MANAGER.provider = None
    MANAGER.state.loaded = False

    events: list[dict] = []
    agen = stream_owner_chat("Tell me a quick hello.")

    async def pump_until_front():
        while True:
            event = await agen.__anext__()
            events.append(event)
            if event.get("type") == "delta" and event.get("lane") == "front":
                return
            if event.get("type") in {"done", "error"}:
                return

    await asyncio.wait_for(pump_until_front(), timeout=2.0)

    assert "front" in order
    assert any(e.get("lane") == "front" for e in events)
    # Weather may have started in parallel, but must not have finished before front.
    assert "weather_done" not in order

    release_weather.set()
    async for event in agen:
        events.append(event)
    assert any(e.get("type") == "done" for e in events)
    assert order.index("front") < order.index("weather_done")


@pytest.mark.asyncio
async def test_conversation_front_before_weather_http(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    order: list[str] = []
    release_weather = asyncio.Event()

    task_id = "conv-front-before-weather"
    async with SessionLocal() as session:
        session.add(
            Task(
                id=task_id,
                title="Hello",
                prompt="Hello there friend",
                status="running",
                stage="act",
                task_class=CONVERSATION_CLASS,
                response_route="direct_reply",
            )
        )
        await session.commit()

    prefetched = FrontReply(
        action="final_basic",
        text="Hello, sir.",
        model="front",
        first_text_ms=2.0,
        complete_ms=2.0,
    )

    async def track_front(*_a, **_k):
        order.append("front")
        return prefetched

    async def slow_weather(prompt: str):
        del prompt
        order.append("weather_start")
        await release_weather.wait()
        order.append("weather_done")
        return None

    async def noop_watchdog(*_a, **_k):
        return None

    monkeypatch.setattr("app.agent.loop.generate_front_reply", track_front)
    monkeypatch.setattr("app.agent.loop.weather_system_message", slow_weather)
    monkeypatch.setattr("app.agent.loop.run_worker_progress_watchdog", noop_watchdog)
    MANAGER.provider = object()
    MANAGER.state.loaded = True
    MANAGER.state.context_size = 16384

    await AGENT._run_conversation(
        task_id,
        "Hello there friend",
        None,
        jarvis_env["settings"],
        WorkingState(goal="Hello there friend", task_class=CONVERSATION_CLASS),
        LiveTaskMetrics(),
    )

    assert order[0] == "front"
    # Terminal fastpath cancels weather; it must not have completed first.
    assert "weather_done" not in order
    release_weather.set()

    async with SessionLocal() as session:
        row = await session.get(Task, task_id)
        assert row is not None
        assert row.status == "completed"
        assert "Hello" in (row.result or "")
