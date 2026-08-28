from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..agent.loop import AGENT
from ..db.models import Task, TaskEvent
from ..db.session import SessionLocal
from ..guests.service import (
    GuestContext,
    GuestPortalError,
    SERVICE,
    extract_guest_token_from_request,
    guest_http_error,
)
from ..guests.schema import PortalLimits, PortalScope

owner_router = APIRouter(prefix="/api/guest-portals", tags=["guest-portals"])
guest_router = APIRouter(prefix="/api/guest", tags=["guest-portal-access"])


class GrantIn(BaseModel):
    resource_type: str
    resource_id: str
    actions: list[str] = Field(default_factory=list)


class PortalLimitsIn(BaseModel):
    single_use: bool = False
    max_sessions: int | None = None
    max_uses: int | None = None


class PortalPreviewIn(BaseModel):
    grants: list[GrantIn] = Field(default_factory=list)
    limits: PortalLimitsIn = Field(default_factory=PortalLimitsIn)
    expires_at: str | None = None


class PortalCreateIn(PortalPreviewIn):
    label: str = "Guest portal"
    guest_label: str = "guest"


def _scope_from_body(body: PortalPreviewIn) -> PortalScope:
    return SERVICE.scope_from_grants([grant.model_dump() for grant in body.grants])


def _limits_from_body(body: PortalPreviewIn) -> PortalLimits:
    return PortalLimits(
        single_use=body.limits.single_use,
        max_sessions=body.limits.max_sessions,
        max_uses=body.limits.max_uses,
    )


async def require_guest(request: Request) -> GuestContext:
    ctx = getattr(request.state, "guest", None)
    if ctx is None:
        raise HTTPException(status_code=401, detail="Guest portal authentication required")
    token = extract_guest_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Guest portal authentication required")
    try:
        return SERVICE.ensure_guest_session(ctx, token)
    except GuestPortalError as exc:
        raise guest_http_error(exc) from exc


def _task_summary(task: Task) -> dict[str, Any]:
    return {
        "id": task.id,
        "title": task.title,
        "status": task.status,
        "stage": task.stage,
        "result": task.result,
        "error": task.error,
        "waiting_for_confirmation": task.waiting_for_confirmation,
        "confirmation_payload": task.confirmation_payload,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
        "finished_at": task.finished_at.isoformat() if task.finished_at else None,
    }


@owner_router.post("/preview")
async def preview_permissions(body: PortalPreviewIn):
    scope = _scope_from_body(body)
    limits = _limits_from_body(body)
    return SERVICE.preview(scope, limits, body.expires_at)


@owner_router.post("")
async def create_portal(body: PortalCreateIn):
    scope = _scope_from_body(body)
    limits = _limits_from_body(body)
    portal, token = SERVICE.create_portal(
        label=body.label,
        guest_label=body.guest_label,
        scope=scope,
        limits=limits,
        expires_at=body.expires_at,
    )
    payload = SERVICE.portal_public_dict(portal)
    payload["token"] = token
    payload["effective_permissions"] = SERVICE.preview(scope, limits, body.expires_at)
    return payload


@owner_router.get("")
async def list_portal_records():
    return [SERVICE.portal_public_dict(portal) for portal in SERVICE.list_portals()]


@owner_router.get("/{portal_id}")
async def get_portal_record(portal_id: str):
    portal = SERVICE.get_portal(portal_id)
    if portal is None:
        raise HTTPException(status_code=404, detail="Portal not found")
    payload = SERVICE.portal_public_dict(portal)
    payload["effective_permissions"] = SERVICE.preview(portal.scope, portal.limits, portal.expires_at)
    return payload


@owner_router.post("/{portal_id}/revoke")
async def revoke_portal_record(portal_id: str):
    try:
        portal = SERVICE.revoke_portal(portal_id)
    except GuestPortalError as exc:
        raise guest_http_error(exc) from exc
    return SERVICE.portal_public_dict(portal)


@owner_router.get("/{portal_id}/audit")
async def portal_audit(portal_id: str, limit: int = 200):
    portal = SERVICE.get_portal(portal_id)
    if portal is None:
        raise HTTPException(status_code=404, detail="Portal not found")
    return SERVICE.list_audit(portal_id=portal_id, limit=limit)


@guest_router.post("/session")
async def start_guest_session(request: Request):
    token = extract_guest_token_from_request(request)
    if not token:
        raise HTTPException(status_code=401, detail="Guest portal token required")
    try:
        ctx = SERVICE.authenticate_guest(token)
    except GuestPortalError as exc:
        raise guest_http_error(exc) from exc
    return {
        "session_id": ctx.session_id,
        "guest_label": ctx.guest_label,
        "portal_id": ctx.portal.id,
        "effective_permissions": SERVICE.effective_permissions(ctx),
    }


@guest_router.get("/session")
async def guest_session(ctx: GuestContext = Depends(require_guest)):
    return {
        "session_id": ctx.session_id,
        "guest_label": ctx.guest_label,
        "portal_id": ctx.portal.id,
        "effective_permissions": SERVICE.effective_permissions(ctx),
    }


@guest_router.get("/tasks/{task_id}")
async def guest_read_task(task_id: str, request: Request, ctx: GuestContext = Depends(require_guest)):
    try:
        SERVICE.authorize(
            ctx,
            resource_type="task",
            resource_id=task_id,
            action="read",
            path=request.url.path,
        )
    except GuestPortalError as exc:
        raise guest_http_error(exc) from exc

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        return _task_summary(task)


@guest_router.get("/tasks/{task_id}/events")
async def guest_query_task_events(task_id: str, request: Request, ctx: GuestContext = Depends(require_guest)):
    try:
        SERVICE.authorize(
            ctx,
            resource_type="task",
            resource_id=task_id,
            action="query",
            path=request.url.path,
        )
    except GuestPortalError as exc:
        raise guest_http_error(exc) from exc

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            raise HTTPException(status_code=404, detail="Task not found")
        events = (
            await session.execute(select(TaskEvent).where(TaskEvent.task_id == task_id).order_by(TaskEvent.id))
        ).scalars().all()
        return {
            "task_id": task_id,
            "events": [
                {
                    "kind": event.kind,
                    "title": event.title,
                    "detail": event.detail,
                    "stage": event.stage,
                    "created_at": event.created_at.isoformat() if event.created_at else None,
                }
                for event in events
            ],
        }


@guest_router.post("/tasks/{task_id}/approve")
async def guest_approve_task(task_id: str, request: Request, ctx: GuestContext = Depends(require_guest)):
    try:
        SERVICE.authorize(
            ctx,
            resource_type="task",
            resource_id=task_id,
            action="approve",
            path=request.url.path,
        )
    except GuestPortalError as exc:
        raise guest_http_error(exc) from exc

    try:
        task = await AGENT.confirm_task(task_id, True)
    except KeyError:
        raise HTTPException(status_code=404, detail="Task not found") from None
    return _task_summary(task)


@guest_router.get("/decisions/{decision_id}")
async def guest_read_decision(decision_id: str, request: Request, ctx: GuestContext = Depends(require_guest)):
    try:
        SERVICE.authorize(
            ctx,
            resource_type="decision_inbox",
            resource_id=decision_id,
            action="read",
            path=request.url.path,
        )
    except GuestPortalError as exc:
        raise guest_http_error(exc) from exc

    # Decision inbox is not yet persisted; return a scoped placeholder envelope.
    return {
        "id": decision_id,
        "status": "unavailable",
        "detail": "Decision inbox backend is not yet available; scope isolation enforced",
    }
