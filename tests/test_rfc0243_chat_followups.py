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
    with pytest.raises(StepBlocked, match="can.t safely resume"):
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


def test_nonstream_deadline_is_never_below_the_prompt_only_budget():
    """A 20k-token prompt at 50 tok/s hits the 180 s first-token cap; its generation budget adds to, never cuts, it."""
    from app.config import InferenceSettings
    from app.inference.stream_deadlines import compute_chat_call_deadline_ms, compute_chat_stream_deadlines
    settings = InferenceSettings()
    first, idle = compute_chat_stream_deadlines(settings, prompt_tokens=20000, prompt_tps=50.0)
    prompt_only = first + idle  # development's non-stream budget (192 s here)
    for max_tokens in (0, 128, 1024, 100000):
        budget = compute_chat_call_deadline_ms(settings, prompt_tokens=20000, prompt_tps=50.0,
                                               max_tokens=max_tokens, generation_tps=10.0)
        assert budget >= prompt_only, (max_tokens, budget, prompt_only)
    assert compute_chat_call_deadline_ms(settings, prompt_tokens=20000, prompt_tps=50.0,
                                         max_tokens=1024, generation_tps=10.0) > prompt_only


def test_nonstream_deadline_honours_an_owner_raised_first_token_cap():
    from app.config import InferenceSettings
    from app.inference.stream_deadlines import compute_chat_call_deadline_ms, compute_chat_stream_deadlines
    settings = InferenceSettings(stream_first_token_max_ms=600000)
    first, idle = compute_chat_stream_deadlines(settings, prompt_tokens=100000, prompt_tps=50.0)
    assert first == 600000
    budget = compute_chat_call_deadline_ms(settings, prompt_tokens=100000, prompt_tps=50.0,
                                           max_tokens=0, generation_tps=10.0)
    assert budget >= first + idle > settings.chat_call_max_ms


@pytest.mark.asyncio
async def test_uncommitted_model_step_with_new_inputs_reruns_and_a_committed_one_stays_blocked(jarvis_env):
    import uuid
    from app.agent.durable_execution.accounting import reset_ledgers
    from app.agent.durable_execution.repository import StepBlocked
    from app.agent.durable_execution.runner import run_model_step
    from app.providers.base import ChatResult
    reset_ledgers()
    run_id = str(uuid.uuid4())
    async with SessionLocal() as session:
        session.add(Task(id=run_id, title="p", prompt="p", status="running", stage="act"))
        await session.commit()

    async def dropped():
        raise RuntimeError("server dropped the connection")  # the attempt never committed

    with pytest.raises(RuntimeError):
        await run_model_step(run_id, "model:1:0:0", predecessor_keys=[], input_fingerprint={"messages": "v1"},
                             operation=dropped)
    calls = []

    async def answer():
        calls.append(1)
        return ChatResult(content="fresh answer")

    # The prompt was rebuilt (fresh retrieval); nothing was committed, so the step runs on the new inputs.
    result = await run_model_step(run_id, "model:1:0:0", predecessor_keys=[], input_fingerprint={"messages": "v2"},
                                  operation=answer)
    assert result.content == "fresh answer" and calls == [1]
    # The re-run recorded the new inputs: the same inputs reuse the committed answer ...
    again = await run_model_step(run_id, "model:1:0:0", predecessor_keys=[], input_fingerprint={"messages": "v2"},
                                 operation=answer)
    assert again.content == "fresh answer" and calls == [1]
    # ... and other inputs never reuse it.
    with pytest.raises(StepBlocked):
        await run_model_step(run_id, "model:1:0:0", predecessor_keys=[], input_fingerprint={"messages": "v3"},
                             operation=answer)
    assert calls == [1]


@pytest.mark.asyncio
async def test_restarted_queued_task_reruns_a_model_step_its_crashed_attempt_never_committed(jarvis_env, monkeypatch):
    """AgentRuntime restarts a queued stable-request_id task with continue_existing=False (model:1 again)."""
    from app.agent.durable_execution.accounting import reset_ledgers
    from app.agent.durable_execution.repository import get_step_by_key
    from app.agent.durable_execution.runner import run_model_step
    from app.agent.durable_execution.types import StepStatus
    from app.agent.loop import AGENT
    from app.providers.base import ChatResult
    reset_ledgers()
    task_id = "restart-uncommitted-model-step"
    target = jarvis_env["tmp"] / "restart-report.txt"
    target.write_text("FOUR")
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title="Restart", prompt=f"Read {target} and report its contents.", status="running",
                         task_class="filesystem", profile="fast", autonomy="autonomous", response_route="managed_task"))
        await session.commit()

    async def crashed():
        raise RuntimeError("worker restarted mid-call")

    # The crashed attempt left model:1:0:0 uncommitted, keyed to inputs the restart rebuilds differently.
    with pytest.raises(RuntimeError):
        await run_model_step(task_id, "model:1:0:0", predecessor_keys=[],
                             input_fingerprint={"messages": "context before the restart"}, operation=crashed)
    monkeypatch.setattr("app.agent.loop.record_trajectory", AsyncMock())
    monkeypatch.setattr("app.agent.loop.publish_owner_text", AsyncMock(return_value={}))

    class Provider:
        name = "scripted"
        model = "scripted-model"

        def __init__(self):
            self.calls = 0

        async def health(self):
            return True

        async def chat(self, messages, tools=None, **kwargs):
            self.calls += 1
            if self.calls in (1, 3) and tools:  # act, then verify, with a real read of the file
                return ChatResult(tool_calls=[{"id": f"restart-read-{self.calls}", "type": "function", "function": {
                    "name": "filesystem", "arguments": json.dumps({"action": "read", "path": str(target)})}}])
            return ChatResult(content="The file says FOUR; read and verified.")

    provider = Provider()
    jarvis_env["manager"].provider = provider
    jarvis_env["settings"].front_responder.enabled = False
    await asyncio.wait_for(AGENT._run(task_id, continue_existing=False), 40)
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
    assert task.status == "completed", (task.status, task.error)
    assert provider.calls >= 1
    assert "start a new model step" not in (task.error or "")
    step = await get_step_by_key(task_id, "model:1:0:0")
    assert step.status == StepStatus.COMPLETED.value


def _model_step_args(run_id):
    from app.agent.durable_execution.types import EffectClass, OperationType, ReplayPolicy
    return dict(run_id=run_id, step_key="model:1:0:0", operation_type=OperationType.MODEL_CALL,
                effect_class=EffectClass.NONE, replay_policy=ReplayPolicy.IDEMPOTENT, predecessor_keys=[],
                result_encoder=lambda value: {"_value": value})


async def _seed_running_task(task_id):
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title="p", prompt="p", status="running", stage="act"))
        await session.commit()


@pytest.mark.asyncio
async def test_new_inputs_never_rebind_a_model_step_under_another_workers_live_lease(jarvis_env):
    """Worker A is mid-call on model:1 with inputs v1; worker B arrives with v2. B is refused without
    touching the step, and A's v1 answer is never served for v2."""
    import uuid
    from app.agent.durable_execution.accounting import reset_ledgers
    from app.agent.durable_execution.repository import StepBlocked, get_step_by_key
    from app.agent.durable_execution.runner import _hash_payload, run_durable_step
    reset_ledgers()
    run_id = str(uuid.uuid4())
    await _seed_running_task(run_id)
    common = _model_step_args(run_id)
    gate, started = asyncio.Event(), asyncio.Event()

    async def a_op():
        started.set()
        await gate.wait()
        return {"content": "answer to v1"}

    async def b_op():
        return {"content": "answer to v2"}

    a = asyncio.create_task(run_durable_step(**common, input_fingerprint={"messages": "v1"}, operation=a_op,
                                             worker_id="worker-A"))
    await started.wait()
    with pytest.raises(StepBlocked):  # A holds the lease
        await run_durable_step(**common, input_fingerprint={"messages": "v2"}, operation=b_op, worker_id="worker-B")
    step = await get_step_by_key(run_id, "model:1:0:0")
    assert step.input_hash == _hash_payload({"messages": "v1"}), "the step keeps A's inputs while A holds the lease"
    gate.set()
    value, meta = await a
    assert value["content"] == "answer to v1" and not meta["reused"]
    with pytest.raises(StepBlocked):  # v1 committed: v2 must never reuse it
        await run_durable_step(**common, input_fingerprint={"messages": "v2"}, operation=b_op, worker_id="worker-B")


@pytest.mark.asyncio
async def test_a_commit_for_inputs_the_step_no_longer_carries_is_rejected(jarvis_env):
    """A's lease expires mid-call; B claims the step for v2, re-runs and commits. A's late v1 commit is refused."""
    import uuid
    from datetime import timedelta
    from sqlalchemy import update
    from app.agent.durable_execution.accounting import reset_ledgers
    from app.agent.durable_execution.repository import StepBlocked, get_step_by_key, load_committed_result
    from app.agent.durable_execution.runner import _hash_payload, run_durable_step
    from app.db.models import ExecutionAttempt, utcnow
    reset_ledgers()
    run_id = str(uuid.uuid4())
    await _seed_running_task(run_id)
    common = _model_step_args(run_id)
    gate, started = asyncio.Event(), asyncio.Event()

    async def a_op():
        started.set()
        await gate.wait()
        return {"content": "answer to v1"}

    async def b_op():
        return {"content": "answer to v2"}

    a = asyncio.create_task(run_durable_step(**common, input_fingerprint={"messages": "v1"}, operation=a_op,
                                             worker_id="worker-A"))
    await started.wait()
    async with SessionLocal() as session:
        await session.execute(update(ExecutionAttempt).where(ExecutionAttempt.worker_id == "worker-A")
                              .values(lease_expires_at=utcnow() - timedelta(seconds=1)))
        await session.commit()
    value, meta = await run_durable_step(**common, input_fingerprint={"messages": "v2"}, operation=b_op,
                                         worker_id="worker-B")
    assert value["content"] == "answer to v2" and not meta["reused"]
    gate.set()
    with pytest.raises(StepBlocked):
        await a
    step = await get_step_by_key(run_id, "model:1:0:0")
    assert step.input_hash == _hash_payload({"messages": "v2"})
    assert (await load_committed_result(step))["_value"]["content"] == "answer to v2"


async def _restart_over_completed_mismatch(jarvis_env, monkeypatch, task_id):
    from app.agent.durable_execution.accounting import reset_ledgers
    from app.agent.durable_execution.repository import get_step_by_key
    from app.agent.durable_execution.runner import run_model_step
    from app.agent.loop import AGENT
    from app.providers.base import ChatResult
    reset_ledgers()
    target = jarvis_env["tmp"] / f"{task_id}.txt"
    target.write_text("FOUR")
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title="Restart", prompt=f"Read {target} and report its contents.", status="running",
                         task_class="filesystem", profile="fast", autonomy="autonomous", response_route="managed_task"))
        await session.commit()

    async def before_crash():
        return ChatResult(content="answer computed for the pre-crash context")

    await run_model_step(task_id, "model:1:0:0", predecessor_keys=[], input_fingerprint={"messages": "pre-crash"},
                         operation=before_crash)
    monkeypatch.setattr("app.agent.loop.record_trajectory", AsyncMock())
    monkeypatch.setattr("app.agent.loop.publish_owner_text", AsyncMock(return_value={}))

    class Provider:
        name = "scripted"
        model = "scripted-model"

        def __init__(self):
            self.calls = 0

        async def health(self):
            return True

        async def chat(self, messages, tools=None, **kwargs):
            self.calls += 1
            return ChatResult(content="fresh")

    provider = Provider()
    jarvis_env["manager"].provider = provider
    jarvis_env["settings"].front_responder.enabled = False
    await asyncio.wait_for(AGENT._run(task_id, continue_existing=False), 40)
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
    error = task.error or ""
    assert task.status == "failed", (task.status, error)
    assert "model step" not in error.lower(), error
    assert provider.calls == 0
    assert await get_step_by_key(task_id, "model:2:0:0") is None
    return task


@pytest.mark.asyncio
async def test_restart_over_a_completed_mismatched_model_step_blocks_the_task(jarvis_env, monkeypatch):
    """CoS ruling: a crashed attempt COMPLETED model:1 for other inputs; the restart (continue_existing=False)
    stops instead of reusing that answer or skipping to model:2. A desktop task (intake chain part, the
    desktop's stable-request_id path) names the desktop's New task action."""
    task = await _restart_over_completed_mismatch(jarvis_env, monkeypatch, "desktop-restart")
    for shown in (task.error, task.result):  # HUD task card (error) and the chat reply (result || error)
        assert "can't safely resume" in shown and "Click New task and ask again" in shown, shown
        assert "new chat" not in shown.lower(), shown


@pytest.mark.asyncio
async def test_restart_over_a_completed_mismatched_model_step_on_the_phone_says_start_a_new_chat(jarvis_env, monkeypatch):
    """The same block on a phone submission (mobile/service.submit retry) names the phone's action."""
    import uuid
    from app.mobile import store
    monkeypatch.setattr(store, "data_dir", lambda: jarvis_env["tmp"])
    task_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "jarvis-mobile:phone-1:req-1"))
    with store.database() as db:
        store.put(db, "submission", task_id, {"fingerprint": "f", "conversation_id": "c", "task_prompt": "p", "profile": "fast"})
    task = await _restart_over_completed_mismatch(jarvis_env, monkeypatch, task_id)
    from app.db.models import Conversation
    from app.mobile.service import conversation_detail
    async with SessionLocal() as session:
        session.add(Conversation(id="phone-chat", task_id=task_id, title="Restart",
                                 messages_json=json.dumps([{"id": "u1", "role": "user", "text": "p", "task_id": task_id}])))
        await session.commit()
    shown = (await conversation_detail("phone-chat"))["messages"][-1]["text"]  # what the phone chat renders
    assert "can't safely resume" in shown and "Start a new chat and ask again" in shown, shown
    assert "New task" not in shown, shown
    # task.error only reaches the desktop (api/tasks), so it keeps the desktop's action.
    assert "Click New task and ask again" in task.error, task.error


async def _seed_step(run_id, input_hash):
    from app.agent.durable_execution.repository import upsert_step
    return await upsert_step(run_id=run_id, step_key="model:1:0:0", predecessor_keys=[], operation_type="model_call",
                             effect_class="none", replay_policy="IDEMPOTENT", input_hash=input_hash, idempotency_key="k0")


@pytest.mark.asyncio
async def test_concurrent_claims_on_one_step_never_both_hold_a_live_lease(jarvis_env):
    """Two claimers for different inputs race on separate pooled connections (aiosqlite threads)."""
    import uuid
    from sqlalchemy import select
    from app.agent.durable_execution.repository import StepBlocked, claim_attempt
    from app.db.models import ExecutionAttempt, ExecutionStep
    for round_ in range(8):
        run_id = str(uuid.uuid4())
        await _seed_running_task(run_id)
        step = await _seed_step(run_id, "h-v0")
        results = await asyncio.gather(
            claim_attempt(step.id, "worker-A", input_hash="h-v1", idempotency_key="k1"),
            claim_attempt(step.id, "worker-B", input_hash="h-v2", idempotency_key="k2"),
            return_exceptions=True)
        winners = [r for r in results if isinstance(r, ExecutionAttempt)]
        assert len(winners) == 1, (round_, results)
        assert all(isinstance(r, (ExecutionAttempt, StepBlocked)) for r in results), results
        async with SessionLocal() as session:
            active = (await session.scalars(select(ExecutionAttempt).where(
                ExecutionAttempt.step_id == step.id, ExecutionAttempt.status == "active"))).all()
            final = await session.get(ExecutionStep, step.id)
        assert [a.worker_id for a in active] == [winners[0].worker_id], (round_, [a.worker_id for a in active])
        assert final.input_hash == {"worker-A": "h-v1", "worker-B": "h-v2"}[winners[0].worker_id]


@pytest.mark.asyncio
async def test_a_claim_racing_a_commit_never_leaves_an_old_answer_under_new_inputs(jarvis_env, monkeypatch):
    """A commits its v1 answer while B claims the step for v2 in the middle of A's commit. Either A wins and B
    is refused, or B wins and A is refused; never a completed step labelled v2 carrying v1's answer."""
    import uuid
    from app.agent.durable_execution import repository as repo
    from app.db.models import ExecutionStep
    run_id = str(uuid.uuid4())
    await _seed_running_task(run_id)
    step = await _seed_step(run_id, "h-v1")
    real_session = repo.SessionLocal
    claim = {}

    class Hooked:
        def __init__(self):
            self._cm = real_session()

        async def __aenter__(self):
            session = await self._cm.__aenter__()
            original_commit = session.commit

            async def commit():
                if "task" not in claim:  # B claims for v2 in the middle of A's commit
                    claim["task"] = asyncio.create_task(
                        repo.claim_attempt(step.id, "worker-B", input_hash="h-v2", idempotency_key="k2"))
                    await asyncio.wait([claim["task"]], timeout=1.0)
                return await original_commit()

            session.commit = commit
            return session

        async def __aexit__(self, *exc):
            return await self._cm.__aexit__(*exc)

    monkeypatch.setattr(repo, "SessionLocal", Hooked)
    a_result = await asyncio.gather(repo.commit_step_result(
        step.id, result={"_value": {"content": "answer to v1"}}, expected_input_hash="h-v1"), return_exceptions=True)
    monkeypatch.setattr(repo, "SessionLocal", real_session)
    b_result = (await asyncio.gather(claim["task"], return_exceptions=True))[0]
    async with real_session() as session:
        final = await session.get(ExecutionStep, step.id)
    assert not (final.status == "completed" and final.input_hash == "h-v2"), (final.input_hash, final.result_json)
    if final.status == "completed":
        assert final.input_hash == "h-v1" and "answer to v1" in final.result_json
        assert isinstance(b_result, repo.StepBlocked), b_result
    else:
        assert isinstance(a_result[0], repo.StepBlocked), a_result


@pytest.mark.asyncio
async def test_a_long_model_call_keeps_its_lease_alive(jarvis_env, monkeypatch):
    """A model call outlives its first lease (here: forced to lapse right after the claim). The runner's
    heartbeat renews it, so worker B with other inputs is still refused mid-call."""
    import uuid
    from datetime import timedelta
    from sqlalchemy import update
    from app.agent.durable_execution.accounting import reset_ledgers
    from app.agent.durable_execution.repository import StepBlocked, get_step_by_key
    from app.agent.durable_execution.runner import _hash_payload, run_durable_step
    from app.db.models import ExecutionAttempt, utcnow
    monkeypatch.setattr("app.agent.durable_execution.runner.HEARTBEAT_INTERVAL_S", 0.05, raising=False)
    reset_ledgers()
    run_id = str(uuid.uuid4())
    await _seed_running_task(run_id)
    common = _model_step_args(run_id)
    gate, started = asyncio.Event(), asyncio.Event()

    async def a_op():
        async with SessionLocal() as session:  # the first 45 s lease has run out
            await session.execute(update(ExecutionAttempt).where(ExecutionAttempt.worker_id == "worker-A")
                                  .values(lease_expires_at=utcnow() - timedelta(seconds=1)))
            await session.commit()
        started.set()
        await gate.wait()
        return {"content": "answer to v1"}

    async def b_op():
        return {"content": "answer to v2"}

    a = asyncio.create_task(run_durable_step(**common, input_fingerprint={"messages": "v1"}, operation=a_op,
                                             worker_id="worker-A"))
    await started.wait()
    await asyncio.sleep(0.4)  # several heartbeat intervals
    with pytest.raises(StepBlocked):
        await run_durable_step(**common, input_fingerprint={"messages": "v2"}, operation=b_op, worker_id="worker-B")
    assert (await get_step_by_key(run_id, "model:1:0:0")).input_hash == _hash_payload({"messages": "v1"})
    gate.set()
    value, meta = await a
    assert value["content"] == "answer to v1" and not meta["reused"]


@pytest.mark.asyncio
async def test_a_superseded_runner_never_overwrites_a_task_another_runner_completed(jarvis_env, monkeypatch):
    """Runner A's model call outlives its lease; runner B claims the same step, commits it and completes the
    task. A's late commit is refused, and A stops without failing the task or replacing B's answer."""
    from datetime import timedelta
    from sqlalchemy import update
    from app.agent.durable_execution.accounting import reset_ledgers
    from app.agent.durable_execution.repository import claim_attempt, commit_step_result, get_step_by_key
    from app.agent.loop import AGENT
    from app.db.models import ExecutionAttempt, utcnow
    from app.providers.base import ChatResult
    reset_ledgers()
    task_id = "superseded-runner"
    target = jarvis_env["tmp"] / "superseded.txt"
    target.write_text("FOUR")
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title="Superseded", prompt=f"Read {target} and report its contents.", status="running",
                         task_class="filesystem", profile="fast", autonomy="autonomous", response_route="managed_task"))
        await session.commit()
    monkeypatch.setattr("app.agent.loop.record_trajectory", AsyncMock())
    monkeypatch.setattr("app.agent.loop.publish_owner_text", AsyncMock(return_value={}))

    class Provider:
        name = "scripted"
        model = "scripted-model"

        def __init__(self):
            self.calls = 0

        async def health(self):
            return True

        async def chat(self, messages, tools=None, **kwargs):
            self.calls += 1
            if self.calls == 1:  # A's lease lapses mid-call; B takes the step over and finishes the task
                step = await get_step_by_key(task_id, "model:1:0:0")
                async with SessionLocal() as session:
                    await session.execute(update(ExecutionAttempt).where(ExecutionAttempt.step_id == step.id)
                                          .values(lease_expires_at=utcnow() - timedelta(seconds=1)))
                    await session.commit()
                await claim_attempt(step.id, "worker-B", input_hash=step.input_hash)
                await commit_step_result(step.id, result={"_value": {"content": "answer from B"}},
                                         expected_input_hash=step.input_hash)
                async with SessionLocal() as session:
                    row = await session.get(Task, task_id)
                    row.status, row.stage, row.result = "completed", "done", "answer from B"
                    await session.commit()
            return ChatResult(content="answer from A")

    provider = Provider()
    jarvis_env["manager"].provider = provider
    jarvis_env["settings"].front_responder.enabled = False
    await asyncio.wait_for(AGENT._run(task_id, continue_existing=False), 40)
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
    assert task.status == "completed", (task.status, task.error)
    assert task.result == "answer from B"
    assert not task.error
    assert provider.calls == 1, "A stopped after its commit was refused"
    step = await get_step_by_key(task_id, "model:1:0:0")
    assert "answer from B" in step.result_json


@pytest.mark.asyncio
async def test_a_late_commit_after_a_takeover_is_superseded_and_keeps_the_new_answer(jarvis_env):
    """rr2 probe 3, as a runner-level test: A's lease lapses mid-call, B re-points the step to v2 and commits;
    A's late v1 commit is refused as superseded, A's attempt ends SUPERSEDED, and B's answer stays."""
    import uuid
    from datetime import timedelta
    from sqlalchemy import update
    from app.agent.durable_execution.accounting import reset_ledgers
    from app.agent.durable_execution.repository import StepSuperseded, get_step_by_key
    from app.agent.durable_execution.runner import _hash_payload, run_durable_step
    from app.db.models import ExecutionAttempt, utcnow
    reset_ledgers()
    run_id = str(uuid.uuid4())
    await _seed_running_task(run_id)
    common = _model_step_args(run_id)
    gate, started = asyncio.Event(), asyncio.Event()

    async def a_op():
        started.set()
        await gate.wait()
        return {"content": "answer to v1"}

    async def b_op():
        return {"content": "answer to v2"}

    a = asyncio.create_task(run_durable_step(**common, input_fingerprint={"messages": "v1"}, operation=a_op,
                                             worker_id="worker-A"))
    await started.wait()
    async with SessionLocal() as session:
        await session.execute(update(ExecutionAttempt).where(ExecutionAttempt.worker_id == "worker-A")
                              .values(lease_expires_at=utcnow() - timedelta(seconds=1)))
        await session.commit()
    await run_durable_step(**common, input_fingerprint={"messages": "v2"}, operation=b_op, worker_id="worker-B")
    gate.set()
    with pytest.raises(StepSuperseded):
        await a
    async with SessionLocal() as session:
        statuses = {x.worker_id: x.status for x in (await session.scalars(select(ExecutionAttempt))).all()
                    if x.worker_id in {"worker-A", "worker-B"}}
    assert statuses == {"worker-A": "superseded", "worker-B": "completed"}, statuses
    step = await get_step_by_key(run_id, "model:1:0:0")
    assert step.input_hash == _hash_payload({"messages": "v2"}) and "answer to v2" in step.result_json
