from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sse_starlette.sse import EventSourceResponse

from ..agent.execution_status import (
    active_worker,
    elapsed_seconds,
    normalized_state,
    phase_for_event,
    project_phase,
    verification_summary,
)
from ..agent.loop import AGENT
from ..agent.self_dev import KillSwitchActive
from ..db.models import Task, TaskEvent
from ..db.session import SessionLocal
from ..events import BUS
from ..agent.tool_exposure import is_full_exposure, tool_names_for
from ..tools.exposure import schema_names
from ..tools.registry import REGISTRY

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    prompt: str
    autonomy: str | None = None
    profile: str | None = None
    execution_mode: str | None = None


class ContinueBody(BaseModel):
    prompt: str | None = None
    approve: bool | None = None


def _iso_utc(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _task_dict(task: Task, last_event: TaskEvent | None = None) -> dict[str, Any]:
    extra: list[str] = []
    raw = getattr(task, "compact_memory", None) or ""
    if raw:
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict) and isinstance(parsed.get("extra_tools"), list):
                extra = [str(item) for item in parsed["extra_tools"]]
        except (TypeError, json.JSONDecodeError):
            extra = []
    task_class = getattr(task, "task_class", None) or ""
    if is_full_exposure(task_class, extra):
        allowed_tools = schema_names(REGISTRY.openai_tools())
    else:
        allowed_tools = sorted(tool_names_for(task_class, extra))
    db_exposed = [item for item in (getattr(task, "exposed_tools", None) or "").split(",") if item]
    runtime = AGENT.runtime_status(task.id)
    state = normalized_state(task)
    heartbeat_status = runtime["heartbeat_status"]
    if state == "waiting":
        heartbeat_status = "waiting"
    elif state in {"queued", "running"} and not runtime["alive"]:
        heartbeat_status = "stale"
    last_progress_at = (
        _iso_utc(last_event.created_at)
        if last_event is not None and last_event.created_at
        else _iso_utc(task.updated_at)
    )
    return {
        "id": task.id,
        "title": task.title,
        "prompt": task.prompt,
        "status": task.status,
        "state": state,
        "stage": task.stage,
        "execution_phase": project_phase(task, last_event).value,
        "autonomy": task.autonomy,
        "profile": task.profile,
        "execution_mode": getattr(task, "execution_mode", None) or "balanced",
        "task_class": task_class,
        "exposed_tools": db_exposed if db_exposed else allowed_tools,
        "allowed_tools": allowed_tools,
        "result": task.result,
        "error": task.error,
        "current_action": task.current_action,
        "current_tool": task.current_tool,
        "active_worker": active_worker(task),
        "retries": task.retries,
        "duration_seconds": task.duration_seconds,
        "elapsed_seconds": elapsed_seconds(task),
        "last_progress_at": last_progress_at,
        "alive": runtime["alive"],
        "last_heartbeat_at": runtime["last_heartbeat_at"],
        "heartbeat_status": heartbeat_status,
        "waiting_for_confirmation": task.waiting_for_confirmation,
        "confirmation_payload": task.confirmation_payload,
        "created_at": _iso_utc(task.created_at),
        "updated_at": _iso_utc(task.updated_at),
        "started_at": _iso_utc(task.started_at),
        "finished_at": _iso_utc(task.finished_at),
        "verification": task.verification,
        "verification_summary": verification_summary(task),
        "model_calls": getattr(task, "model_calls", 0) or 0,
        "tool_calls": getattr(task, "tool_call_count", 0) or 0,
        "schema_errors": getattr(task, "schema_errors", 0) or 0,
        "model_ms": getattr(task, "model_ms", 0) or 0,
        "tool_ms": getattr(task, "tool_ms", 0) or 0,
        "human_interventions": getattr(task, "human_interventions", 0) or 0,
    }


@router.post("")
async def create_task(body: TaskCreate):
    try:
        task = await AGENT.create_task(body.prompt, body.autonomy, body.profile, body.execution_mode)
    except KillSwitchActive as exc:
        raise HTTPException(409, str(exc)) from exc
    return _task_dict(task)


@router.get("")
async def list_tasks():
    async with SessionLocal() as session:
        rows = (await session.execute(select(Task).order_by(Task.created_at.desc()))).scalars().all()
        latest_ids = select(func.max(TaskEvent.id)).group_by(TaskEvent.task_id)
        events = (
            await session.execute(select(TaskEvent).where(TaskEvent.id.in_(latest_ids)))
        ).scalars().all()
        latest: dict[str, TaskEvent] = {}
        for event in events:
            latest.setdefault(event.task_id, event)
        return [_task_dict(row, latest.get(row.id)) for row in rows]


@router.get("/{task_id}")
async def get_task(task_id: str):
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        events = (
            await session.execute(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id))
        ).scalars().all()
        last_event = events[-1] if events else None
        payload = _task_dict(task, last_event)
        payload["events"] = [
            {
                "kind": e.kind,
                "title": e.title,
                "detail": e.detail,
                "stage": e.stage,
                "phase": phase_for_event(e).value,
                "source": e.source,
                "created_at": _iso_utc(e.created_at),
            }
            for e in events
        ]
        return payload


@router.post("/{task_id}/continue")
async def continue_task(task_id: str, body: ContinueBody | None = None):
    body = body or ContinueBody()
    try:
        if body.approve is not None:
            task = await AGENT.confirm_task(task_id, body.approve)
        else:
            task = await AGENT.continue_task(task_id, body.prompt)
        return _task_dict(task)
    except KillSwitchActive as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError:
        raise HTTPException(404, "Task not found")


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    AGENT.cancel(task_id)
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        task.status = "cancelled"
        task.stage = "cancelled"
        await session.commit()
        return _task_dict(task)


@router.get("/{task_id}/events")
async def task_events(task_id: str):
    return EventSourceResponse(BUS.stream(task_id))
