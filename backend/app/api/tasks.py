from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sse_starlette.sse import EventSourceResponse

from ..agent.loop import AGENT
from ..db.models import Task, TaskEvent
from ..db.session import SessionLocal
from ..events import BUS

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class TaskCreate(BaseModel):
    prompt: str
    autonomy: str | None = None
    profile: str | None = None
    execution_mode: str | None = None


class ContinueBody(BaseModel):
    prompt: str | None = None
    approve: bool | None = None


def _task_dict(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "prompt": task.prompt,
        "status": task.status,
        "stage": task.stage,
        "autonomy": task.autonomy,
        "profile": task.profile,
        "execution_mode": getattr(task, "execution_mode", None) or "balanced",
        "task_class": getattr(task, "task_class", None) or "",
        "acceptance_criteria": task.acceptance_criteria,
        "current_action": task.current_action,
        "current_tool": task.current_tool,
        "exposed_tools": [item for item in (getattr(task, "exposed_tools", None) or "").split(",") if item],
        "result": task.result,
        "error": task.error,
        "retries": task.retries,
        "duration_seconds": task.duration_seconds,
        "waiting_for_confirmation": task.waiting_for_confirmation,
        "confirmation_payload": task.confirmation_payload,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
        "verification": task.verification,
    }


@router.post("")
async def create_task(body: TaskCreate):
    task = await AGENT.create_task(body.prompt, body.autonomy, body.profile, body.execution_mode)
    return _task_dict(task)


@router.get("")
async def list_tasks():
    async with SessionLocal() as session:
        rows = (await session.execute(select(Task).order_by(Task.created_at.desc()))).scalars().all()
        return [_task_dict(row) for row in rows]


@router.get("/{task_id}")
async def get_task(task_id: str):
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(404, "Task not found")
        events = (
            await session.execute(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id))
        ).scalars().all()
        payload = _task_dict(task)
        payload["events"] = [
            {
                "kind": e.kind,
                "title": e.title,
                "detail": e.detail,
                "stage": e.stage,
                "created_at": e.created_at.isoformat() if e.created_at else None,
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
