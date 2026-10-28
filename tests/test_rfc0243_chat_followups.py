import asyncio
import json
from unittest.mock import AsyncMock
from sqlalchemy import select

import pytest

from app.agent.compaction import deserialize_messages, serialize_messages
from app.agent.loop import AgentRuntime
from app.db.models import Task, TaskEvent
from app.db.session import SessionLocal
from app.events import EventBus
from app.providers.base import ChatMessage


@pytest.mark.asyncio
async def test_followup_drains_original_runner_and_background_jobs_before_saving(jarvis_env, monkeypatch):
    runtime = AgentRuntime()
    task_id = "followup-drain"
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title="Original", prompt="Original question", status="running",
                         result="Original answer", conversation_json=serialize_messages([
                             ChatMessage(role="user", content="Original question"),
                             ChatMessage(role="assistant", content="Original answer"),
                         ])))
        await session.commit()
    old_started = asyncio.Event()
    old_stopped = asyncio.Event()
    child_started = asyncio.Event()
    child_stopped = asyncio.Event()

    async def old_runner():
        old_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            # Reproduce a late write from the original request during cleanup.
            await asyncio.sleep(0)
            async with SessionLocal() as session:
                row = await session.get(Task, task_id)
                row.result = "Old cleanup answer"
                await session.commit()
            old_stopped.set()

    async def background():
        child_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            child_stopped.set()

    old = runtime._start_runner(task_id, old_runner())
    child = runtime._spawn_turn_job(task_id, background())
    await old_started.wait()
    await child_started.wait()

    async def new_runner(ident, *, continue_existing, extra_prompt):
        assert old_stopped.is_set() and child_stopped.is_set()
        assert extra_prompt == "New question"
        async with SessionLocal() as session:
            row = await session.get(Task, ident)
            assert row.result == "" and row.error == ""
            assert deserialize_messages(row.conversation_json)[-1].content == "New question"

    monkeypatch.setattr(runtime, "_run", new_runner)
    await runtime.continue_task(task_id, "New question")
    await runtime._tasks[task_id]
    assert old.done() and child.done()
    async with SessionLocal() as session:
        row = await session.get(Task, task_id)
        history = deserialize_messages(row.conversation_json)
        assert [m.content for m in history] == ["Original question", "Original answer", "New question"]
        boundaries = (await session.execute(select(TaskEvent).where(TaskEvent.task_id == task_id))).scalars().all()
        assert any(event.kind == "owner_turn_started" for event in boundaries)


@pytest.mark.asyncio
async def test_old_done_callback_does_not_cancel_replacement_heartbeat(jarvis_env):
    runtime = AgentRuntime()
    old_done = asyncio.Event()
    async def old_runner():
        await old_done.wait()
    async def new_runner():
        await asyncio.Event().wait()
    old = runtime._start_runner("heartbeat-turn", old_runner())
    new = runtime._start_runner("heartbeat-turn", new_runner())
    heartbeat = runtime._heartbeat_tasks["heartbeat-turn"]
    old_done.set()
    await old
    await asyncio.sleep(0)
    assert runtime._heartbeat_tasks["heartbeat-turn"] is heartbeat
    assert not heartbeat.done()
    await runtime._stop_previous_turn("heartbeat-turn")
    assert new.done()


@pytest.mark.asyncio
async def test_current_turn_stream_does_not_replay_original_reply(jarvis_env):
    bus = EventBus()
    task_id = "followup-events"
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title="Chat", prompt="Original", status="running"))
        await session.commit()
    await bus.publish(task_id, "front_response_completed", "Reply", json.dumps({"text": "Original answer"}))
    await bus.publish(task_id, "owner_turn_started", "New owner turn")
    await bus.publish(task_id, "front_response_completed", "Reply", json.dumps({"text": "New answer"}))
    current = bus.stream(task_id, current_turn=True)
    first = await current.__anext__()
    await current.aclose()
    assert "New answer" in first and "Original answer" not in first
    history = bus.stream(task_id)
    original = await history.__anext__()
    await history.aclose()
    assert "Original answer" in original


@pytest.mark.asyncio
async def test_two_questions_reach_inference_and_second_gets_its_own_answer(jarvis_env, monkeypatch):
    from app.inference.manager import MANAGER
    runtime = AgentRuntime()
    jarvis_env["settings"].front_responder.enabled = False
    monkeypatch.setattr("app.persona.session_state.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.agent.loop.weather_system_message", AsyncMock(return_value=None))
    seen = []
    first = "How are you this evening?"
    second = "And what is your name?"

    class Provider:
        async def chat_stream(self, messages, **kwargs):
            current = [message.content for message in messages if message.role == "user"][-1]
            seen.append(current)
            yield "My name is Anzu." if current == second else "I am ready to help."
        async def chat(self, *args, **kwargs):
            raise AssertionError("Plain follow-up should not replay a tool task")

    MANAGER.provider = Provider()
    task = await runtime.create_task(first)
    await runtime._tasks[task.id]
    await runtime.continue_task(task.id, second)
    await runtime._tasks[task.id]
    assert seen == [first, second]
    async with SessionLocal() as session:
        row = await session.get(Task, task.id)
        assert row.status == "completed"
        assert row.result == "My name is Anzu."
        users = [message.content for message in deserialize_messages(row.conversation_json) if message.role == "user"]
        assert users == [first, second]
