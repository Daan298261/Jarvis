from __future__ import annotations

import asyncio
import json
from collections import defaultdict
from datetime import timezone
from typing import Any, AsyncIterator

from sqlalchemy import select

from .db.models import TaskEvent, utcnow
from .db.session import SessionLocal


def _iso_utc(value) -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


class EventBus:
    def __init__(self) -> None:
        self._subscribers: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._global: list[asyncio.Queue] = []

    def subscribe(self, task_id: str | None = None) -> asyncio.Queue:
        queue: asyncio.Queue = asyncio.Queue()
        if task_id:
            self._subscribers[task_id].append(queue)
        else:
            self._global.append(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue, task_id: str | None = None) -> None:
        if task_id and queue in self._subscribers.get(task_id, []):
            self._subscribers[task_id].remove(queue)
        if queue in self._global:
            self._global.remove(queue)

    async def publish(
        self,
        task_id: str,
        kind: str,
        title: str,
        detail: str = "",
        stage: str = "",
        *,
        source: str = "jarvis-agent",
        persist: bool = True,
    ) -> None:
        event = {
            "task_id": task_id,
            "kind": kind,
            "title": title,
            "detail": detail,
            "stage": stage,
            "source": source,
            "created_at": utcnow().isoformat(),
        }
        if persist:
            async with SessionLocal() as session:
                session.add(
                    TaskEvent(
                        task_id=task_id,
                        kind=kind,
                        title=title[:400],
                        detail=detail,
                        stage=stage,
                        source=source,
                    )
                )
                await session.commit()
        for queue in list(self._subscribers.get(task_id, [])) + list(self._global):
            await queue.put(event)

    async def publish_ephemeral(self, channel: str, kind: str, title: str, detail: str = "", stage: str = "") -> None:
        """Notify subscribers without persisting a TaskEvent (no task FK)."""
        await self.publish(channel, kind, title, detail, stage, persist=False)

    async def stream(self, task_id: str | None = None) -> AsyncIterator[str]:
        queue = self.subscribe(task_id)
        try:
            if task_id:
                async with SessionLocal() as session:
                    rows = (
                        await session.execute(
                            select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id)
                        )
                    ).scalars().all()
                    for row in rows:
                        payload = {
                            "task_id": row.task_id,
                            "kind": row.kind,
                            "title": row.title,
                            "detail": row.detail,
                            "stage": row.stage,
                            "source": row.source,
                            "created_at": _iso_utc(row.created_at),
                        }
                        yield f"data: {json.dumps(payload)}\n\n"
            while True:
                event = await queue.get()
                yield f"data: {json.dumps(event)}\n\n"
        finally:
            self.unsubscribe(queue, task_id)


BUS = EventBus()
