from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from typing import Any

from .schema import JarvisTrajectoryV1

logger = logging.getLogger(__name__)

_queue: deque[JarvisTrajectoryV1] = deque()
_lock = threading.Lock()
_pending: list[JarvisTrajectoryV1] = []
_consumer_task: asyncio.Task | None = None


def enqueue_trajectory(trajectory: JarvisTrajectoryV1) -> None:
    """Queue a normalized trajectory for asynchronous memory/skill consumption."""
    with _lock:
        _queue.append(trajectory)


def drain_pending_trajectories() -> list[JarvisTrajectoryV1]:
    with _lock:
        items = list(_queue)
        _queue.clear()
        return items


def peek_pending_trajectories() -> list[JarvisTrajectoryV1]:
    with _lock:
        return list(_queue)


def record_consumed(trajectory: JarvisTrajectoryV1, *, result: dict[str, Any] | None = None) -> None:
    _pending.append(trajectory)
    if len(_pending) > 200:
        del _pending[:-200]


def consumed_trajectories() -> list[JarvisTrajectoryV1]:
    return list(_pending)


async def _consume_loop() -> None:
    while True:
        batch = drain_pending_trajectories()
        if not batch:
            await asyncio.sleep(0.05)
            continue
        for trajectory in batch:
            try:
                await _handle_trajectory(trajectory)
            except Exception:
                logger.exception("trajectory consumer failed for %s", trajectory.trajectory_id)


async def _handle_trajectory(trajectory: JarvisTrajectoryV1) -> None:
    """Lightweight async hook for the memory/skill pipeline."""
    from ..agent.skills import note_imported_trajectory_evidence

    result = await note_imported_trajectory_evidence(trajectory)
    record_consumed(trajectory, result=result)


def ensure_consumer_started() -> None:
    global _consumer_task
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    if _consumer_task is None or _consumer_task.done():
        _consumer_task = loop.create_task(_consume_loop())


def reset_consumer_state() -> None:
    global _consumer_task
    with _lock:
        _queue.clear()
    _pending.clear()
    if _consumer_task is not None and not _consumer_task.done():
        _consumer_task.cancel()
    _consumer_task = None
