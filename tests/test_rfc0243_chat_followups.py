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


@pytest.mark.asyncio
async def test_worker_followup_does_not_reuse_original_model_steps(jarvis_env, monkeypatch):
    from app.agent.durable_execution.repository import list_steps
    from app.agent.durable_execution.runner import run_model_step
    from app.providers.base import ChatResult

    task_id = "worker-followup"
    target = jarvis_env["tmp"] / "briefing.txt"
    target.write_text("Updated briefing content")
    first = f"Read the file {target} and report its contents."
    second = f"Read the file {target} again and report the updated contents."
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title="Briefing", prompt=first, status="running",
                         task_class="filesystem", profile="fast", autonomy="autonomous",
                         result="Original briefing answer", conversation_json=serialize_messages([
                             ChatMessage(role="system", content="Existing authorized file inspection."),
                             ChatMessage(role="user", content=first),
                             ChatMessage(role="assistant", content="Original briefing answer"),
                         ])))
        await session.commit()
    await run_model_step(task_id, "model:1:0:0", predecessor_keys=[],
                         input_fingerprint={"old": True},
                         operation=AsyncMock(return_value=ChatResult(content="Original briefing answer")))
    jarvis_env["settings"].front_responder.enabled = False
    monkeypatch.setattr("app.agent.loop.record_trajectory", AsyncMock())
    monkeypatch.setattr("app.agent.loop.publish_owner_text", AsyncMock(return_value={}))
    seen = []

    class Provider:
        name = "scripted"
        async def health(self):
            return True
        async def chat(self, messages, tools=None, **kwargs):
            seen.append(list(messages))
            if len(seen) == 1 and tools:
                return ChatResult(tool_calls=[{"id": "read-updated", "type": "function", "function": {
                    "name": "filesystem", "arguments": json.dumps({"action": "read", "path": str(target)})}}])
            return ChatResult(content="Updated briefing content inspected and verified.")

    jarvis_env["manager"].provider = Provider()
    runtime = AgentRuntime()
    await runtime.continue_task(task_id, second)
    await asyncio.wait_for(runtime._tasks[task_id], 35)
    assert seen and any(second in str(message.content) for message in seen[0])
    steps = await list_steps(task_id)
    assert any(step.step_key.startswith("model:2:") for step in steps)
    async with SessionLocal() as session:
        row = await session.get(Task, task_id)
        assert row.status == "completed", row.error
        assert "Updated briefing content" in row.result
        replayed = (await session.scalars(select(TaskEvent).where(
            TaskEvent.task_id == task_id, TaskEvent.kind == "step_reused"))).all()
        assert not any('"step_key": "model:1:' in event.detail for event in replayed)


@pytest.mark.asyncio
async def test_durable_model_rejects_changed_inputs_even_with_same_step_key(jarvis_env):
    from app.agent.durable_execution.repository import StepBlocked
    from app.agent.durable_execution.runner import run_model_step
    from app.providers.base import ChatResult

    async with SessionLocal() as session:
        session.add(Task(id="cache-inputs", title="Cache", prompt="First", status="running"))
        await session.commit()
    operation = AsyncMock(return_value=ChatResult(content="First answer"))
    await run_model_step("cache-inputs", "model:1", predecessor_keys=[],
                         input_fingerprint={"prompt": "First question"}, operation=operation)
    with pytest.raises(StepBlocked, match="different inputs"):
        await run_model_step("cache-inputs", "model:1", predecessor_keys=[],
                             input_fingerprint={"prompt": "Other question"}, operation=operation)
    assert operation.await_count == 1


@pytest.mark.asyncio
async def test_overflow_adopts_actual_server_limit_and_retries_fitted_prompt(jarvis_env):
    import httpx
    from openai import APIStatusError
    from app.inference.manager import InferenceManager
    from app.inference.prompt_budget import estimate_prompt_tokens
    from app.providers.base import ChatResult

    manager = InferenceManager()
    manager.state.context_size = manager.state.server_n_ctx = 32768
    calls = []
    class Provider:
        async def chat(self, messages, **kwargs):
            calls.append(messages)
            if len(calls) == 1:
                response = httpx.Response(400, request=httpx.Request("POST", "http://localhost/v1/chat/completions"))
                raise APIStatusError("The model is loaded with context length of only 4096 tokens", response=response, body=None)
            assert manager.live_context_size() == 4096
            assert estimate_prompt_tokens(messages) + kwargs["max_tokens"] < 4096
            return ChatResult(content="Answer to the latest question")
    manager.provider = Provider()
    result = await manager.chat([
        ChatMessage(role="system", content="Prior context " * 1300),
        ChatMessage(role="user", content="The latest question"),
    ], max_tokens=256, settings=jarvis_env["settings"])
    assert result.content == "Answer to the latest question"
    assert len(calls) == 2
    assert calls[-1][-1].content == "The latest question"


def test_context_failure_retains_server_reason_when_local_estimate_fits():
    from app.inference.prompt_budget import calculate_prompt_budget, context_capacity_error, server_context_limit
    from app.inference.profiles import PROFILES
    budget = calculate_prompt_budget([ChatMessage(role="user", content="Short question")], None,
                                     profile=PROFILES["balanced"], max_tokens=128, active_context=32768)
    reason = "maximum context length is 4096 tokens"
    assert server_context_limit(RuntimeError(reason)) == 4096
    assert server_context_limit(RuntimeError("request contains 7390 tokens")) is None
    assert "Server response: " + reason in context_capacity_error(budget, server_error=reason)
    assert "despite the local token estimate" in context_capacity_error(budget, server_error=reason)


def test_nonstream_deadline_includes_generation_and_stays_bounded():
    from app.config import InferenceSettings
    from app.inference.stream_deadlines import compute_chat_call_deadline_ms
    settings = InferenceSettings()
    small = compute_chat_call_deadline_ms(settings, prompt_tokens=1000, prompt_tps=100,
                                          max_tokens=128, generation_tps=10)
    large = compute_chat_call_deadline_ms(settings, prompt_tokens=1000, prompt_tps=100,
                                          max_tokens=1024, generation_tps=10)
    assert large - small == 89600
    assert large > 35800
    assert compute_chat_call_deadline_ms(settings, prompt_tokens=10000, prompt_tps=10,
                                         max_tokens=10000, generation_tps=1) == settings.chat_call_max_ms


@pytest.mark.asyncio
async def test_generation_budget_uses_rate_rather_than_output_token_count(monkeypatch):
    from app.inference.manager import InferenceManager
    monkeypatch.setattr("app.inference.benchmarks.record_benchmark_sample", AsyncMock())
    manager = InferenceManager()
    await manager.record_timings({"predicted_n": 640})
    assert manager.state.generation_tps is None
    await manager.record_timings({"predicted_n": 640, "predicted_ms": 64000})
    assert manager.state.generation_tps == 10
    await manager.record_timings({"predicted_per_second": 20, "predicted_n": 640, "predicted_ms": 64000})
    assert manager.state.generation_tps == 20
