from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agent.delegation import DelegationError, MANAGER, _event_dict, _worker_dict

router = APIRouter(prefix="/api/delegation", tags=["delegation"])


class SpawnChildBody(BaseModel):
    task: str
    parent_worker_id: str | None = None
    context: dict[str, Any] = Field(default_factory=dict)
    tools: list[str] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    deadline_at: datetime | None = None
    result_schema: dict[str, Any] = Field(default_factory=dict)
    autonomy: str | None = None
    privacy_class: str | None = None
    ttl_seconds: int | None = None


class CompleteBody(BaseModel):
    result: dict[str, Any] = Field(default_factory=dict)


class FailBody(BaseModel):
    error: str


def _http_error(exc: DelegationError) -> HTTPException:
    status = 404 if exc.code.endswith("not_found") else 400
    if exc.code in {"max_depth_exceeded", "max_fan_out_exceeded"}:
        status = 409
    return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})


@router.post("/parents/{parent_task_id}/children")
async def spawn_child(parent_task_id: str, body: SpawnChildBody):
    try:
        worker = await MANAGER.spawn_child(
            parent_task_id,
            body.task,
            parent_worker_id=body.parent_worker_id,
            context=body.context,
            tools=body.tools,
            budget=body.budget,
            deadline_at=body.deadline_at,
            result_schema=body.result_schema,
            autonomy=body.autonomy,
            privacy_class=body.privacy_class,
            ttl_seconds=body.ttl_seconds,
        )
    except DelegationError as exc:
        raise _http_error(exc) from exc
    return _worker_dict(worker)


@router.get("/parents/{parent_task_id}/children")
async def list_children(parent_task_id: str, parent_worker_id: str | None = None):
    rows = await MANAGER.list_children(parent_task_id, parent_worker_id)
    return [_worker_dict(row) for row in rows]


@router.get("/parents/{parent_task_id}/events")
async def list_parent_events(parent_task_id: str):
    rows = await MANAGER.list_events(parent_task_id)
    return [_event_dict(row) for row in rows]


@router.get("/workers/{worker_id}")
async def get_worker(worker_id: str):
    worker = await MANAGER.get_worker(worker_id)
    if not worker:
        raise HTTPException(404, "Worker not found")
    return _worker_dict(worker)


@router.post("/workers/{worker_id}/start")
async def start_worker(worker_id: str):
    try:
        worker = await MANAGER.start_worker(worker_id)
    except DelegationError as exc:
        raise _http_error(exc) from exc
    return _worker_dict(worker)


@router.post("/workers/{worker_id}/complete")
async def complete_worker(worker_id: str, body: CompleteBody | None = None):
    body = body or CompleteBody()
    try:
        worker = await MANAGER.complete_worker(worker_id, body.result)
    except DelegationError as exc:
        raise _http_error(exc) from exc
    return _worker_dict(worker)


@router.post("/workers/{worker_id}/fail")
async def fail_worker(worker_id: str, body: FailBody):
    try:
        worker = await MANAGER.fail_worker(worker_id, body.error)
    except DelegationError as exc:
        raise _http_error(exc) from exc
    return _worker_dict(worker)
