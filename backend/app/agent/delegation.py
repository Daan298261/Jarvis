from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from ..config import load_settings
from ..db.models import DelegatedWorker, DelegationEvent, Task, utcnow
from ..db.session import SessionLocal
from ..events import BUS

AUTONOMY_RANK: dict[str, int] = {
    "interactive": 0,
    "trusted": 1,
    "autonomous": 2,
}

PRIVACY_RANK: dict[str, int] = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
}

DEFAULT_MAX_DEPTH = 3
DEFAULT_MAX_FAN_OUT = 5
DEFAULT_TTL_SECONDS = 300
PLATFORM_AUTONOMY_CAP = "autonomous"

ACTIVE_STATUSES = frozenset({"pending", "running"})


class DelegationError(Exception):
    def __init__(self, message: str, code: str = "delegation_error") -> None:
        super().__init__(message)
        self.code = code


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _rank(table: dict[str, int], value: str, default: int = 0) -> int:
    return table.get((value or "").strip().lower(), default)


def _autonomy_at_rank(rank: int) -> str:
    for name, value in AUTONOMY_RANK.items():
        if value == rank:
            return name
    return "interactive"


def _privacy_at_rank(rank: int) -> str:
    for name, value in PRIVACY_RANK.items():
        if value == rank:
            return name
    return "public"


def clamp_autonomy(
    requested: str,
    parent_autonomy: str,
    platform_cap: str = PLATFORM_AUTONOMY_CAP,
) -> str:
    max_rank = min(_rank(AUTONOMY_RANK, parent_autonomy), _rank(AUTONOMY_RANK, platform_cap))
    child_rank = min(_rank(AUTONOMY_RANK, requested), max_rank)
    return _autonomy_at_rank(child_rank)


def clamp_privacy_class(
    requested: str,
    parent_privacy: str,
    platform_cap: str = "restricted",
) -> str:
    parent_rank = _rank(PRIVACY_RANK, parent_privacy)
    platform_rank = _rank(PRIVACY_RANK, platform_cap)
    min_rank = max(parent_rank, _rank(PRIVACY_RANK, requested))
    max_rank = min(platform_rank, 3)
    return _privacy_at_rank(min(min_rank, max_rank))


def _parse_json(value: str | dict[str, Any] | list[Any] | None, default: Any) -> Any:
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _subset_tools(child_tools: list[str], parent_tools: list[str]) -> list[str]:
    parent_set = {item.strip().lower() for item in parent_tools if item}
    if not parent_set:
        return []
    out: list[str] = []
    for item in child_tools:
        key = str(item or "").strip().lower()
        if not key:
            continue
        if key not in parent_set:
            raise DelegationError(f"Tool '{key}' is not allowed for the parent worker", "tool_not_allowed")
        out.append(key)
    return sorted(set(out))


def _subset_context(child_context: dict[str, Any], parent_context: dict[str, Any]) -> dict[str, Any]:
    if not child_context:
        return {}
    for key in child_context:
        if key not in parent_context:
            raise DelegationError(f"Context key '{key}' was not delegated by the parent", "context_not_allowed")
    return dict(child_context)


def _clamp_budget(child_budget: dict[str, Any], parent_budget: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in child_budget.items():
        if not isinstance(value, (int, float)):
            continue
        parent_value = parent_budget.get(key)
        if isinstance(parent_value, (int, float)):
            out[key] = min(value, parent_value)
        else:
            out[key] = value
    return out


def _worker_dict(worker: DelegatedWorker) -> dict[str, Any]:
    return {
        "id": worker.id,
        "parent_task_id": worker.parent_task_id,
        "parent_worker_id": worker.parent_worker_id,
        "depth": worker.depth,
        "task": worker.task,
        "context": _parse_json(worker.context_json, {}),
        "tools": _parse_json(worker.tools_json, []),
        "budget": _parse_json(worker.budget_json, {}),
        "result_schema": _parse_json(worker.result_schema_json, {}),
        "autonomy": worker.autonomy,
        "privacy_class": worker.privacy_class,
        "status": worker.status,
        "result": _parse_json(worker.result_json, None),
        "error": worker.error,
        "created_at": worker.created_at.isoformat() if worker.created_at else None,
        "updated_at": worker.updated_at.isoformat() if worker.updated_at else None,
        "started_at": worker.started_at.isoformat() if worker.started_at else None,
        "finished_at": worker.finished_at.isoformat() if worker.finished_at else None,
        "deadline_at": worker.deadline_at.isoformat() if worker.deadline_at else None,
        "expires_at": worker.expires_at.isoformat() if worker.expires_at else None,
    }


def _event_dict(event: DelegationEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "parent_task_id": event.parent_task_id,
        "worker_id": event.worker_id,
        "kind": event.kind,
        "title": event.title,
        "detail": event.detail,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


class DelegationManager:
    def __init__(self) -> None:
        self._timers: dict[str, asyncio.Task] = {}
        self._running: set[str] = set()

    def max_depth(self) -> int:
        settings = load_settings()
        value = getattr(settings, "delegation_max_depth", None)
        return int(value) if value is not None else DEFAULT_MAX_DEPTH

    def max_fan_out(self) -> int:
        settings = load_settings()
        value = getattr(settings, "delegation_max_fan_out", None)
        return int(value) if value is not None else DEFAULT_MAX_FAN_OUT

    async def _publish_parent_event(
        self,
        parent_task_id: str,
        worker_id: str,
        kind: str,
        title: str,
        detail: str = "",
    ) -> None:
        async with SessionLocal() as session:
            session.add(
                DelegationEvent(
                    parent_task_id=parent_task_id,
                    worker_id=worker_id,
                    kind=kind,
                    title=title[:400],
                    detail=detail,
                )
            )
            await session.commit()
        payload = {
            "worker_id": worker_id,
            "kind": kind,
            "title": title,
            "detail": detail,
        }
        await BUS.publish(parent_task_id, f"delegation.{kind}", title, json.dumps(payload), stage="delegation")

    async def _parent_authority(
        self,
        parent_task_id: str,
        parent_worker_id: str | None,
    ) -> tuple[str, str, list[str], dict[str, Any], dict[str, Any], int]:
        async with SessionLocal() as session:
            task = await session.get(Task, parent_task_id)
            if not task:
                raise DelegationError("Parent task not found", "parent_not_found")

            if parent_worker_id:
                parent_worker = await session.get(DelegatedWorker, parent_worker_id)
                if not parent_worker or parent_worker.parent_task_id != parent_task_id:
                    raise DelegationError("Parent worker not found", "parent_not_found")
                if parent_worker.status not in ACTIVE_STATUSES:
                    raise DelegationError("Parent worker is not active", "parent_not_active")
                autonomy = parent_worker.autonomy
                privacy = parent_worker.privacy_class
                tools = _parse_json(parent_worker.tools_json, [])
                context = _parse_json(parent_worker.context_json, {})
                budget = _parse_json(parent_worker.budget_json, {})
                depth = parent_worker.depth
            else:
                autonomy = task.autonomy
                privacy = "internal"
                from .tool_exposure import tool_names_for

                tools = sorted(tool_names_for(task.task_class or ""))
                context = {"task_prompt": task.prompt, "task_class": task.task_class or ""}
                budget = {}
                depth = 0

        return autonomy, privacy, tools, context, budget, depth

    async def spawn_child(
        self,
        parent_task_id: str,
        task: str,
        *,
        parent_worker_id: str | None = None,
        context: dict[str, Any] | None = None,
        tools: list[str] | None = None,
        budget: dict[str, Any] | None = None,
        deadline_at: datetime | None = None,
        result_schema: dict[str, Any] | None = None,
        autonomy: str | None = None,
        privacy_class: str | None = None,
        ttl_seconds: int | None = None,
    ) -> DelegatedWorker:
        await self.expire_stale_workers(parent_task_id)

        if not task.strip():
            raise DelegationError("Delegated task cannot be empty", "invalid_task")

        parent_autonomy, parent_privacy, parent_tools, parent_context, parent_budget, parent_depth = (
            await self._parent_authority(parent_task_id, parent_worker_id)
        )

        child_depth = parent_depth + 1
        if child_depth > self.max_depth():
            raise DelegationError(
                f"Maximum delegation depth ({self.max_depth()}) exceeded",
                "max_depth_exceeded",
            )

        async with SessionLocal() as session:
            fan_out_query = select(func.count()).select_from(DelegatedWorker).where(
                DelegatedWorker.parent_task_id == parent_task_id,
                DelegatedWorker.parent_worker_id == parent_worker_id,
                DelegatedWorker.status.in_(tuple(ACTIVE_STATUSES)),
            )
            active_children = (await session.execute(fan_out_query)).scalar_one()
            if active_children >= self.max_fan_out():
                raise DelegationError(
                    f"Maximum fan-out ({self.max_fan_out()}) exceeded for this parent",
                    "max_fan_out_exceeded",
                )

        child_context = _subset_context(context or {}, parent_context)
        child_tools = _subset_tools(tools or [], parent_tools)
        child_budget = _clamp_budget(budget or {}, parent_budget)
        child_autonomy = clamp_autonomy(autonomy or parent_autonomy, parent_autonomy)
        child_privacy = clamp_privacy_class(privacy_class or parent_privacy, parent_privacy)

        now = utcnow()
        ttl = ttl_seconds or DEFAULT_TTL_SECONDS
        deadline = _as_utc(deadline_at) or (now + timedelta(seconds=ttl))
        expires = min(deadline, now + timedelta(seconds=ttl))

        worker = DelegatedWorker(
            id=str(uuid.uuid4()),
            parent_task_id=parent_task_id,
            parent_worker_id=parent_worker_id,
            depth=child_depth,
            task=task.strip(),
            context_json=json.dumps(child_context),
            tools_json=json.dumps(child_tools),
            budget_json=json.dumps(child_budget),
            result_schema_json=json.dumps(result_schema or {}),
            autonomy=child_autonomy,
            privacy_class=child_privacy,
            status="pending",
            deadline_at=deadline,
            expires_at=expires,
            created_at=now,
            updated_at=now,
        )

        async with SessionLocal() as session:
            session.add(worker)
            await session.commit()
            await session.refresh(worker)

        await self._publish_parent_event(
            parent_task_id,
            worker.id,
            "spawned",
            "Child worker spawned",
            json.dumps({"depth": child_depth, "tools": child_tools}),
        )
        self._schedule_expiry(worker.id, expires)
        return worker

    def _schedule_expiry(self, worker_id: str, expires_at: datetime) -> None:
        delay = max(0.0, (expires_at - utcnow()).total_seconds())
        if worker_id in self._timers:
            self._timers[worker_id].cancel()
        self._timers[worker_id] = asyncio.create_task(self._expire_after(worker_id, delay))

    async def _expire_after(self, worker_id: str, delay: float) -> None:
        try:
            await asyncio.sleep(delay)
            await self._expire_worker(worker_id, reason="deadline reached")
        except asyncio.CancelledError:
            return

    async def _expire_worker(self, worker_id: str, reason: str = "expired") -> bool:
        async with SessionLocal() as session:
            worker = await session.get(DelegatedWorker, worker_id)
            if not worker or worker.status not in ACTIVE_STATUSES:
                return False
            worker.status = "expired"
            worker.error = reason
            worker.finished_at = utcnow()
            worker.updated_at = utcnow()
            parent_task_id = worker.parent_task_id
            await session.commit()

        self._running.discard(worker_id)
        timer = self._timers.pop(worker_id, None)
        if timer and not timer.done():
            timer.cancel()

        await self._publish_parent_event(
            parent_task_id,
            worker_id,
            "expired",
            "Child worker expired",
            reason,
        )
        return True

    async def expire_stale_workers(self, parent_task_id: str | None = None) -> int:
        now = utcnow()
        async with SessionLocal() as session:
            query = select(DelegatedWorker).where(
                DelegatedWorker.status.in_(tuple(ACTIVE_STATUSES)),
                DelegatedWorker.expires_at <= now,
            )
            if parent_task_id:
                query = query.where(DelegatedWorker.parent_task_id == parent_task_id)
            rows = (await session.execute(query)).scalars().all()
            worker_ids = [row.id for row in rows]

        expired = 0
        for worker_id in worker_ids:
            if await self._expire_worker(worker_id, reason="automatic expiry"):
                expired += 1
        return expired

    async def get_worker(self, worker_id: str) -> DelegatedWorker | None:
        await self.expire_stale_workers()
        async with SessionLocal() as session:
            return await session.get(DelegatedWorker, worker_id)

    async def list_children(
        self,
        parent_task_id: str,
        parent_worker_id: str | None = None,
    ) -> list[DelegatedWorker]:
        await self.expire_stale_workers(parent_task_id)
        async with SessionLocal() as session:
            query = select(DelegatedWorker).where(DelegatedWorker.parent_task_id == parent_task_id)
            if parent_worker_id is None:
                query = query.where(DelegatedWorker.parent_worker_id.is_(None))
            else:
                query = query.where(DelegatedWorker.parent_worker_id == parent_worker_id)
            query = query.order_by(DelegatedWorker.created_at)
            return list((await session.execute(query)).scalars().all())

    async def list_events(self, parent_task_id: str) -> list[DelegationEvent]:
        async with SessionLocal() as session:
            rows = (
                await session.execute(
                    select(DelegationEvent)
                    .where(DelegationEvent.parent_task_id == parent_task_id)
                    .order_by(DelegationEvent.id)
                )
            ).scalars().all()
            return list(rows)

    async def complete_worker(self, worker_id: str, result: dict[str, Any] | None = None) -> DelegatedWorker:
        await self.expire_stale_workers()
        async with SessionLocal() as session:
            worker = await session.get(DelegatedWorker, worker_id)
            if not worker:
                raise DelegationError("Worker not found", "worker_not_found")
            if worker.status not in ACTIVE_STATUSES:
                raise DelegationError(f"Worker is not active ({worker.status})", "worker_not_active")

            worker.status = "completed"
            worker.result_json = json.dumps(result or {})
            worker.finished_at = utcnow()
            worker.updated_at = utcnow()
            if not worker.started_at:
                worker.started_at = worker.finished_at
            parent_task_id = worker.parent_task_id
            await session.commit()
            await session.refresh(worker)

        self._running.discard(worker_id)
        timer = self._timers.pop(worker_id, None)
        if timer and not timer.done():
            timer.cancel()

        await self._publish_parent_event(
            parent_task_id,
            worker_id,
            "result",
            "Child worker completed",
            json.dumps(result or {}),
        )
        return worker

    async def fail_worker(self, worker_id: str, error: str) -> DelegatedWorker:
        await self.expire_stale_workers()
        async with SessionLocal() as session:
            worker = await session.get(DelegatedWorker, worker_id)
            if not worker:
                raise DelegationError("Worker not found", "worker_not_found")
            if worker.status not in ACTIVE_STATUSES:
                raise DelegationError(f"Worker is not active ({worker.status})", "worker_not_active")

            worker.status = "failed"
            worker.error = error
            worker.finished_at = utcnow()
            worker.updated_at = utcnow()
            if not worker.started_at:
                worker.started_at = worker.finished_at
            parent_task_id = worker.parent_task_id
            await session.commit()
            await session.refresh(worker)

        self._running.discard(worker_id)
        timer = self._timers.pop(worker_id, None)
        if timer and not timer.done():
            timer.cancel()

        await self._publish_parent_event(
            parent_task_id,
            worker_id,
            "failure",
            "Child worker failed",
            error,
        )
        return worker

    async def start_worker(self, worker_id: str) -> DelegatedWorker:
        await self.expire_stale_workers()
        async with SessionLocal() as session:
            worker = await session.get(DelegatedWorker, worker_id)
            if not worker:
                raise DelegationError("Worker not found", "worker_not_found")
            if worker.status != "pending":
                raise DelegationError(f"Worker is not pending ({worker.status})", "worker_not_active")

            worker.status = "running"
            worker.started_at = utcnow()
            worker.updated_at = utcnow()
            parent_task_id = worker.parent_task_id
            await session.commit()
            await session.refresh(worker)

        self._running.add(worker_id)
        await self._publish_parent_event(
            parent_task_id,
            worker_id,
            "status",
            "Child worker running",
        )
        return worker


MANAGER = DelegationManager()
