"""Recoverable optional work that must never hold up delivery of a result.

Separate serial delivery and learning lanes bound DB pressure and promotion races.
Jobs become eligible only after the completed event is durably published.
The outbox is at-least-once: handlers must tolerate replay after a crash.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import timedelta

from sqlalchemy import exists, or_, select
from sqlalchemy.orm import aliased

from ..db.models import PostResponseJob, Task, TaskEvent, utcnow
from ..db.session import SessionLocal
from ..events import BUS
from .planning import CONVERSATION_CLASS, MANAGED_TASK, WorkingState

log = logging.getLogger(__name__)
_workers: dict[str, asyncio.Task] = {}
_stopping = False
_wake: dict[str, asyncio.Event] = {}
MAX_ATTEMPTS = 3
JOB_TIMEOUT = 60.0


def stage_jobs(session, task_id: str, working: WorkingState | None, verified: bool) -> None:
    """Called inside the result transaction; no extra foreground commit."""
    payloads = {"speech": {}}
    if working is not None:
        payloads.update(trajectory={"working": working.dumps()}, usage={"verified": verified}, promotion={})
    for kind, payload in payloads.items():
        session.add(PostResponseJob(task_id=task_id, kind=kind, payload=json.dumps(payload)))


async def execute(job: PostResponseJob) -> None:
    payload = json.loads(job.payload)
    if job.kind == "speech":
        from ..persona.narrator import speak_outcome, forget_task

        async with SessionLocal() as session:
            task = await session.get(Task, job.task_id)
            if task is None:
                return
            speak = task.response_route == MANAGED_TASK or bool(task.task_class and task.task_class != CONVERSATION_CLASS)
            result = task.result or ""
        if speak:
            await speak_outcome(job.task_id, success=True, result=result, error="")
        else:
            forget_task(job.task_id)
    elif job.kind == "trajectory":
        from .trajectory import record_trajectory

        await record_trajectory(job.task_id, WorkingState.loads(payload["working"]), "completed", idempotent=True)
    elif job.kind == "usage":
        from ..coding.usage import record_task_usage

        await record_task_usage(job.task_id, "completed", verified=payload["verified"], idempotent=True)
    elif job.kind == "promotion":
        from .skills import promote_from_trajectories

        # Wait until this task's trajectory has actually been written.
        async with SessionLocal() as session:
            trajectory = await session.get(PostResponseJob, (job.task_id, "trajectory"))
            if trajectory and trajectory.status != "done":
                raise RuntimeError("trajectory enrichment is not ready")
        for skill in await promote_from_trajectories():
            await BUS.publish(job.task_id, "memory_updated", f"Promoted reusable skill: {skill.name}",
                              skill.description[:800], stage="completed")
    else:
        raise ValueError(f"Unknown post-response job: {job.kind}")


async def _drain(lane: str) -> None:
    while not _stopping:
        wake = _wake[lane]
        wake.clear()
        delivered = exists().where(TaskEvent.task_id == PostResponseJob.task_id, TaskEvent.kind == "completed")
        dependency = aliased(PostResponseJob)
        pending_trajectory = exists().where(
            dependency.task_id == PostResponseJob.task_id, dependency.kind == "trajectory",
            dependency.status == "pending",
        )
        async with SessionLocal() as session:
            job = await session.scalar(select(PostResponseJob).where(
                PostResponseJob.status == "pending", delivered,
                or_(PostResponseJob.kind != "promotion", ~pending_trajectory),
                (PostResponseJob.kind == "speech") if lane == "delivery" else (PostResponseJob.kind != "speech"),
            ).order_by(PostResponseJob.available_at, PostResponseJob.task_id, PostResponseJob.kind).limit(1))
        if job is None:
            await wake.wait()
            continue
        delay = (job.available_at.replace(tzinfo=None) - utcnow().replace(tzinfo=None)).total_seconds()
        if delay > 0:
            await asyncio.sleep(min(delay, 1.0))
            continue
        started = time.perf_counter()
        try:
            async with asyncio.timeout(JOB_TIMEOUT):
                await execute(job)
        except asyncio.CancelledError:
            raise  # Leave pending for startup recovery.
        except Exception as exc:
            job.attempts += 1
            job.last_error = type(exc).__name__  # Do not persist exception text containing private inputs.
            job.available_at = utcnow() + timedelta(seconds=2 ** job.attempts)
            if job.attempts >= MAX_ATTEMPTS:
                job.status = "failed"
            log.warning("Post-response job %s/%s attempt %d: %s", job.task_id, job.kind, job.attempts, job.last_error)
        else:
            job.status = "done"
            job.last_error = ""
            job.payload = "{}"  # Drop the working-state snapshot after successful enrichment.
        async with SessionLocal() as session:
            await session.merge(job)
            await session.commit()
        log.info("Post-response %s/%s %s in %.1f ms", job.task_id, job.kind, job.status,
                 (time.perf_counter() - started) * 1000)


def start() -> None:
    global _stopping
    _stopping = False
    for lane in ("delivery", "learning"):
        if lane not in _workers or _workers[lane].done():
            _wake[lane] = asyncio.Event()
            _workers[lane] = asyncio.create_task(_drain(lane), name=f"post-response-{lane}")
            _workers[lane].add_done_callback(_finished)
        _wake[lane].set()


def _finished(task: asyncio.Task) -> None:
    if not task.cancelled() and task.exception() is not None:
        log.error("Post-response worker stopped", exc_info=task.exception())


async def recover() -> None:
    """Close the crash window between result commit and completion publication."""
    async with SessionLocal() as session:
        ids = (await session.scalars(select(PostResponseJob.task_id).where(
            PostResponseJob.status == "pending",
        ).distinct())).all()
    for task_id in ids:
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            event = await session.scalar(select(TaskEvent.id).where(
                TaskEvent.task_id == task_id, TaskEvent.kind == "completed",
            ).limit(1))
            if task is None or task.status != "completed" or event is not None:
                continue
            result = task.result or ""
        await BUS.publish(task_id, "completed", "Task completed", result[:2000], stage="completed")
    start()


async def stop() -> None:
    global _stopping
    _stopping = True
    for worker in _workers.values():
        worker.cancel()
    await asyncio.gather(*_workers.values(), return_exceptions=True)
    _workers.clear()
    _wake.clear()
