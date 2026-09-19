"""RFC-0127: progress feedback when the worker lane is slow."""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from sqlalchemy import select

from ..config import AppSettings, load_settings
from ..db.models import Task, TaskEvent
from ..db.session import SessionLocal
from ..events import BUS
from ..persona.chat_delivery import publish_owner_text
from ..persona.think_aloud import progress_think_aloud_line
from .front_responder import generate_progress_update

logger = logging.getLogger(__name__)

WORKER_PROGRESS_FIRST_DELAY_SECONDS = 60.0
WORKER_PROGRESS_REPEAT_COOLDOWN_SECONDS = 50.0

_worker_useful_text: dict[str, bool] = {}
_last_progress_monotonic: dict[str, float] = {}


def reset_worker_progress_state() -> None:
    _worker_useful_text.clear()
    _last_progress_monotonic.clear()


def mark_worker_useful_owner_text(task_id: str) -> None:
    _worker_useful_text[task_id] = True


def clear_worker_progress_for_task(task_id: str) -> None:
    _worker_useful_text.pop(task_id, None)
    _last_progress_monotonic.pop(task_id, None)


def worker_useful_text_seen(task_id: str) -> bool:
    return bool(_worker_useful_text.get(task_id))


async def latest_task_progress_context(task_id: str) -> str:
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(TaskEvent)
                .where(TaskEvent.task_id == task_id)
                .where(TaskEvent.kind.in_(("stage", "progress", "ingress_size_classified")))
                .order_by(TaskEvent.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
    if not row:
        return "Work is still in progress."
    stage = (row.stage or "").strip()
    title = (row.title or "").strip()
    detail = (row.detail or "").strip()[:240]
    bits = [bit for bit in (stage, title, detail) if bit]
    return " · ".join(bits) if bits else "Work is still in progress."


def progress_cooldown_elapsed(task_id: str, *, now: float | None = None) -> bool:
    stamp = _last_progress_monotonic.get(task_id)
    if not stamp:
        return True
    current = time.monotonic() if now is None else now
    return (current - stamp) >= WORKER_PROGRESS_REPEAT_COOLDOWN_SECONDS


def _mark_progress_emitted(task_id: str, *, now: float | None = None) -> None:
    _last_progress_monotonic[task_id] = time.monotonic() if now is None else now


async def emit_worker_progress_update(
    task_id: str,
    *,
    context: str | None = None,
    settings: AppSettings | None = None,
) -> dict[str, Any] | None:
    app = settings or load_settings()
    if not progress_cooldown_elapsed(task_id):
        return None
    situation = (context or "").strip() or await latest_task_progress_context(task_id)
    line = await generate_progress_update(situation, settings=app)
    if not line:
        line = progress_think_aloud_line(situation)
    if not line:
        return None
    _mark_progress_emitted(task_id)
    delivery = await publish_owner_text(
        line,
        title="Jarvis",
        kind="assistant",
        source="think_aloud",
        speak=True,
    )
    await BUS.publish(
        task_id,
        "progress",
        "Still working",
        line[:1500],
        stage="chat",
    )
    logger.info("Worker progress for %s (%s chars)", task_id, len(line))
    return delivery


async def run_worker_progress_watchdog(
    task_id: str,
    *,
    turn_started: float,
    settings: AppSettings | None = None,
    should_continue: Callable[[], bool | Awaitable[bool]] | None = None,
    sleep: Callable[[float], Awaitable[None]] | None = None,
    monotonic: Callable[[], float] | None = None,
    perf_counter: Callable[[], float] | None = None,
) -> None:
    app = settings or load_settings()
    _sleep = sleep or asyncio.sleep
    _mono = monotonic or time.monotonic
    _perf = perf_counter or time.perf_counter

    async def _alive() -> bool:
        if should_continue is not None:
            outcome = should_continue()
            if asyncio.iscoroutine(outcome):
                outcome = await outcome
            if not outcome:
                return False
        async with SessionLocal() as session:
            task = await session.get(Task, task_id)
            if not task or task.status in {"completed", "failed", "cancelled"}:
                return False
        return True

    try:
        while await _alive():
            elapsed = _perf() - turn_started
            wait_for = WORKER_PROGRESS_FIRST_DELAY_SECONDS - elapsed
            if wait_for > 0:
                await _sleep(wait_for)
            if not await _alive():
                break
            if worker_useful_text_seen(task_id):
                break
            if not progress_cooldown_elapsed(task_id, now=_mono()):
                await _sleep(WORKER_PROGRESS_REPEAT_COOLDOWN_SECONDS)
                continue
            await emit_worker_progress_update(task_id, settings=app)
            await _sleep(WORKER_PROGRESS_REPEAT_COOLDOWN_SECONDS)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.debug("Worker progress watchdog stopped for %s: %s", task_id, exc)


async def task_still_running(task_id: str) -> bool:
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        return bool(task and task.status in {"queued", "running", "waiting"})
