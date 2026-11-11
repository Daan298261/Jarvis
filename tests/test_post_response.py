import asyncio
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from app.agent import post_response
from app.agent.loop import AGENT
from app.agent.metrics import LiveTaskMetrics
from app.agent.planning import WorkingState
from app.db.models import CodingUsageSample, ExecutionAttempt, ExecutionStep, PostResponseJob, Task, TaskEvent, Trajectory
from app.db.session import SessionLocal
from app.events import BUS


async def seed(task_id="response", working=None, publish=True, task_class="mixed"):
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title="Read clock", prompt="Read clock", status="completed",
                         result="The time is 12:00", response_route="direct_lookup", task_class=task_class))
        post_response.stage_jobs(session, task_id, working, True)
        await session.commit()
    if publish:
        await BUS.publish(task_id, "completed", "Task completed", "The time is 12:00")


async def wait_done():
    async with asyncio.timeout(5):
        while True:
            async with SessionLocal() as session:
                count = await session.scalar(select(func.count()).select_from(PostResponseJob).where(
                    PostResponseJob.status == "pending"))
            if not count:
                return
            await asyncio.sleep(0.01)


@pytest.fixture(autouse=True)
async def worker_lifecycle(monkeypatch, _database_engine_hygiene_after_test):
    monkeypatch.setattr("app.persona.narrator.speak_outcome", AsyncMock())
    monkeypatch.setattr("app.agent.skills.promote_from_trajectories", AsyncMock(return_value=[]))
    yield
    await post_response.stop()


async def test_completion_is_published_while_memory_is_blocked(jarvis_env, monkeypatch):
    entered, release = asyncio.Event(), asyncio.Event()

    async def blocked_memory(*args, **kwargs):
        entered.set()
        await release.wait()

    monkeypatch.setattr("app.agent.trajectory.record_trajectory", blocked_memory)
    monkeypatch.setattr(AGENT, "_await_managed_front", AsyncMock())
    monkeypatch.setattr(AGENT, "_release_lazy_vision", AsyncMock())
    async with SessionLocal() as session:
        session.add(Task(id="response", title="Read clock", prompt="Read clock", status="running",
                         response_route="direct_lookup", task_class="mixed"))
        await session.commit()
    queue = BUS.subscribe("response")
    try:
        assert await asyncio.wait_for(AGENT._complete("response", [], "The time is 12:00", "verified",
                                                      working=WorkingState(goal="Read clock")), 3)
        await asyncio.wait_for(entered.wait(), 3)
        events = []
        while not queue.empty():
            events.append(queue.get_nowait())
        assert any(event["kind"] == "completed" for event in events)
        assert not release.is_set()
        async with SessionLocal() as session:
            assert (await session.get(Task, "response")).status == "completed"
            assert (await session.get(PostResponseJob, ("response", "trajectory"))).status == "pending"
        release.set()
        await wait_done()
    finally:
        BUS.unsubscribe(queue, "response")


async def test_unpublished_jobs_wait_then_recover_missing_event(jarvis_env, monkeypatch):
    handler = AsyncMock()
    monkeypatch.setattr(post_response, "execute", handler)
    await seed(publish=False)
    post_response.start()
    await asyncio.sleep(0.05)
    handler.assert_not_awaited()
    await post_response.recover()
    await wait_done()
    handler.assert_awaited_once()
    # Re-running startup recovery must not publish or execute duplicates.
    await post_response.recover()
    await wait_done()
    handler.assert_awaited_once()
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(TaskEvent).where(
            TaskEvent.kind == "completed")) == 1


async def test_shutdown_leaves_interrupted_work_recoverable(jarvis_env, monkeypatch):
    entered = asyncio.Event()

    async def blocked(job):
        entered.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(post_response, "execute", blocked)
    await seed()
    post_response.start()
    await asyncio.wait_for(entered.wait(), 2)
    await post_response.stop()
    async with SessionLocal() as session:
        assert (await session.get(PostResponseJob, ("response", "speech"))).status == "pending"
    handler = AsyncMock()
    monkeypatch.setattr(post_response, "execute", handler)
    await post_response.recover()
    await wait_done()
    handler.assert_awaited_once()


async def test_failed_job_does_not_block_other_jobs_or_change_answer(jarvis_env, monkeypatch):
    async def handler(job):
        if job.task_id == "broken":
            raise RuntimeError("private input must not be saved")

    monkeypatch.setattr(post_response, "execute", handler)
    monkeypatch.setattr(post_response, "MAX_ATTEMPTS", 1)
    await seed("broken")
    await seed("healthy")
    post_response.start()
    await wait_done()
    async with SessionLocal() as session:
        failed = await session.get(PostResponseJob, ("broken", "speech"))
        assert failed.status == "failed" and failed.attempts == 1
        assert failed.last_error == "RuntimeError"
        assert (await session.get(PostResponseJob, ("healthy", "speech"))).status == "done"
        assert (await session.get(Task, "broken")).result == "The time is 12:00"


async def test_transient_failure_retries_and_clears_snapshot(jarvis_env, monkeypatch):
    handler = AsyncMock(side_effect=[RuntimeError("temporary"), None])
    monkeypatch.setattr(post_response, "execute", handler)
    await seed()
    post_response.start()
    post_response.start()  # Repeated arrivals share the same serial worker.
    await wait_done()
    assert handler.await_count == 2
    async with SessionLocal() as session:
        job = await session.get(PostResponseJob, ("response", "speech"))
        assert job.status == "done" and job.attempts == 1
        assert job.last_error == "" and job.payload == "{}"


async def test_outbox_rolls_back_with_result_transaction(jarvis_env):
    async with SessionLocal() as session:
        session.add(Task(id="rollback", title="test", prompt="test", status="completed"))
        post_response.stage_jobs(session, "rollback", WorkingState(goal="test"), True)
        await session.flush()
        await session.rollback()
    async with SessionLocal() as session:
        assert await session.get(Task, "rollback") is None
        assert await session.scalar(select(func.count()).select_from(PostResponseJob)) == 0


async def test_slow_learning_does_not_delay_delivery_of_next_response(jarvis_env, monkeypatch):
    learning_started, next_delivery = asyncio.Event(), asyncio.Event()

    async def handler(job):
        if job.kind != "speech":
            learning_started.set()
            await asyncio.Event().wait()
        elif job.task_id == "next":
            next_delivery.set()

    monkeypatch.setattr(post_response, "execute", handler)
    await seed(working=WorkingState(goal="Read clock"))
    post_response.start()
    await asyncio.wait_for(learning_started.wait(), 2)
    await seed("next")
    post_response.start()
    await asyncio.wait_for(next_delivery.wait(), 2)


async def test_timed_out_optional_work_is_retained_as_failed(jarvis_env, monkeypatch):
    async def handler(job):
        await asyncio.Event().wait()

    monkeypatch.setattr(post_response, "execute", handler)
    monkeypatch.setattr(post_response, "JOB_TIMEOUT", 0.02)
    monkeypatch.setattr(post_response, "MAX_ATTEMPTS", 1)
    await seed()
    post_response.start()
    await wait_done()
    async with SessionLocal() as session:
        job = await session.get(PostResponseJob, ("response", "speech"))
        assert job.status == "failed" and job.last_error == "TimeoutError"


async def test_replaying_handlers_does_not_duplicate_memory_or_usage(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.trajectories.store.save_trajectory", lambda row: row)
    monkeypatch.setattr("app.trajectories.consumer.enqueue_trajectory", lambda row: None)
    await seed(working=WorkingState(goal="Read clock"), task_class="software engineering")
    async with SessionLocal() as session:
        jobs = (await session.scalars(select(PostResponseJob).where(
            PostResponseJob.kind.in_(("trajectory", "usage"))))).all()
    for job in jobs:
        await post_response.execute(job)
        await post_response.execute(job)
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(Trajectory)) == 1
        assert await session.scalar(select(func.count()).select_from(CodingUsageSample)) == 1


async def test_requested_memory_write_still_blocks_unearned_confirmation(jarvis_env):
    working = WorkingState(goal="Remember that my favorite color is blue")
    assert not await AGENT._complete("missing-task", [], working.goal, "verified", working=working)
    async with SessionLocal() as session:
        assert await session.scalar(select(func.count()).select_from(PostResponseJob)) == 0


def test_model_wall_time_is_accounted_without_provider_timings():
    metrics = LiveTaskMetrics()
    metrics.note_model({"provider_wall_ms": 1234})
    assert metrics.model_calls == 1 and metrics.model_ms == 1234
    metrics.note_model({"prompt_ms": 20, "predicted_ms": 30})
    assert metrics.model_ms == 1284


async def test_durable_result_and_attempt_commit_together_and_replay_once(jarvis_env):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from app.agent.durable_execution.crash import SimulatedWorkerDeath, crash_at
    from app.agent.durable_execution.runner import run_durable_step
    from app.agent.durable_execution.types import CrashBoundary, EffectClass, OperationType, ReplayPolicy

    async with SessionLocal() as session:
        session.add(Task(id="durable", title="test", prompt="test", status="running"))
        await session.commit()
    commits = []
    def committed(session):
        commits.append(1)

    calls = []
    async def operation():
        calls.append(1)
        async with SessionLocal() as session:
            step = await session.scalar(select(ExecutionStep).where(ExecutionStep.run_id == "durable"))
            attempt = await session.scalar(select(ExecutionAttempt).where(ExecutionAttempt.step_id == step.id))
            assert step.status == "running" and attempt.status == "active"
        return "evidence"

    kwargs = dict(run_id="durable", step_key="read", operation_type=OperationType.INTERNAL,
                  effect_class=EffectClass.INTERNAL, replay_policy=ReplayPolicy.IDEMPOTENT,
                  predecessor_keys=[], input_fingerprint={}, operation=operation,
                  result_encoder=lambda value: {"_value": value})
    event.listen(Session, "after_commit", committed)
    try:
        with crash_at("read", CrashBoundary.AFTER_COMMIT):
            with pytest.raises(SimulatedWorkerDeath):
                await run_durable_step(**kwargs)
        assert len(commits) == 3  # Insert step; claim+running; result+finished attempt.
    finally:
        event.remove(Session, "after_commit", committed)
    async with SessionLocal() as session:
        step = await session.scalar(select(ExecutionStep).where(ExecutionStep.run_id == "durable"))
        attempt = await session.scalar(select(ExecutionAttempt).where(ExecutionAttempt.step_id == step.id))
        assert step.status == "completed" and attempt.status == "completed"
    result, meta = await run_durable_step(**kwargs)
    assert result == "evidence" and meta["reused"] and len(calls) == 1
