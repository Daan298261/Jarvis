from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..auth import require_owner_private_key
from ..db.models import Task
from ..db.session import SessionLocal
from ..mobile import identity, scheduler, service
from ..mobile.store import database, get, put, root, rows

router = APIRouter(prefix="/api/companion", tags=["companion"])
owner_router = APIRouter(prefix="/api/mobile/manage", dependencies=[Depends(require_owner_private_key)], tags=["mobile management"])
Device = Depends(identity.require_device)


class Enroll(BaseModel):
    invitation: str = Field(min_length=20, max_length=100)
    public_key: str = Field(max_length=2000)
    name: str = Field(min_length=1, max_length=100)


class Proof(BaseModel):
    device_id: uuid.UUID
    signature: str = Field(max_length=512)


class Confirm(BaseModel):
    fingerprint: str = Field(min_length=64, max_length=64)


class Message(BaseModel):
    request_id: uuid.UUID
    text: str = Field(min_length=1, max_length=32000)
    profile: str = "auto"
    conversation_id: uuid.UUID | None = None
    attachments: list[uuid.UUID] = Field(default_factory=list, max_length=10)


class Schedule(BaseModel):
    prompt: str = Field(min_length=1, max_length=32000)
    profile: str = "auto"
    next_run: float = Field(gt=0)
    timezone: str = "Europe/Amsterdam"
    recurrence: Literal["once", "daily", "weekly"] = "once"


class Preferences(BaseModel):
    notifications: bool | None = None
    critical_calls: bool | None = None
    push_token: str | None = Field(default=None, max_length=4096)


@router.post("/enroll")
def enroll(body: Enroll):
    return identity.enroll(body.invitation, body.public_key, body.name)


@router.get("/challenge/{device_id}")
def challenge(device_id: uuid.UUID):
    return identity.challenge(str(device_id))


@router.post("/session")
def session(body: Proof):
    return identity.exchange(str(body.device_id), body.signature)


@router.get("/capabilities")
def capabilities(device=Device):
    from ..workers.voice import voice_status
    from ..mobile.calls import capabilities as call_capabilities
    return {"api_version": 1, "device": identity.safe_device(device), "voice": voice_status(),
            "calls": call_capabilities(), "studio": service.studio_capabilities(),
            "attachments_max_bytes": 64 * 1024 * 1024, "schedules": True}


@router.get("/models")
def models(device=Device):
    return service.models()


@router.get("/conversations")
async def conversations(device=Device):
    return await service.conversations()


@router.get("/conversations/{conversation_id}")
async def conversation(conversation_id: uuid.UUID, device=Device):
    return await service.conversation_detail(str(conversation_id))


@router.post("/messages")
async def message(body: Message, device=Device):
    if not body.text.strip():
        raise HTTPException(400, "Message is empty")
    return await service.submit(device["id"], str(body.request_id), body.text, body.profile,
                                str(body.conversation_id) if body.conversation_id else None,
                                [str(item) for item in body.attachments])


@router.get("/tasks")
async def tasks(device=Device):
    async with SessionLocal() as db:
        task_ids = (await db.execute(select(Task.id).order_by(Task.created_at.desc()).limit(50))).scalars().all()
    return [await service.task_snapshot(task_id) for task_id in task_ids]


@router.get("/tasks/{task_id}")
async def task(task_id: uuid.UUID, device=Device):
    return await service.task_snapshot(str(task_id))


@router.post("/tasks/{task_id}/cancel")
async def cancel(task_id: uuid.UUID, device=Device):
    from .tasks import cancel_task
    await service.task_snapshot(str(task_id))
    return await cancel_task(str(task_id))


@router.get("/events")
async def events(after: int = Query(0, ge=0), device=Device):
    return await service.events(after)


@router.post("/attachments")
async def upload(request: Request, device=Device):
    attachment_id = str(uuid.uuid4())
    folder = root() / "attachments"
    folder.mkdir(exist_ok=True)
    path = folder / attachment_id
    size = 0
    try:
        with path.open("xb") as output:
            async for chunk in request.stream():
                size += len(chunk)
                if size > 64 * 1024 * 1024:
                    raise HTTPException(413, "Attachment exceeds 64 MiB")
                output.write(chunk)
        if not size:
            raise HTTPException(400, "Attachment is empty")
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    value = {"id": attachment_id, "device_id": device["id"], "name": request.headers.get("x-filename", "attachment")[:200],
             "content_type": request.headers.get("content-type", "application/octet-stream")[:100], "size": size}
    with database() as db:
        put(db, "attachment", attachment_id, value)
    return value


@router.get("/attachments/{attachment_id}")
def download(attachment_id: uuid.UUID, device=Device):
    with database() as db:
        item = get(db, "attachment", str(attachment_id))
    if not item or item["device_id"] != device["id"]:
        raise HTTPException(404, "Attachment not found")
    return FileResponse(root() / "attachments" / item["id"], filename=item["name"], media_type="application/octet-stream")


@router.post("/voice/transcribe")
async def transcribe(request: Request, device=Device):
    from ..workers.voice import transcribe_audio, VoiceSTTError
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > 16 * 1024 * 1024:
            raise HTTPException(413, "Voice recording exceeds 16 MiB")
    try:
        return {"text": await transcribe_audio(bytes(data), "mobile.m4a")}
    except (VoiceSTTError, RuntimeError) as exc:
        raise HTTPException(503, str(exc))


class Speak(BaseModel):
    text: str = Field(min_length=1, max_length=6000)


@router.post("/voice/speak")
async def speak(body: Speak, device=Device):
    from ..workers.voice import synthesize_speech
    try:
        return Response(await synthesize_speech(body.text), media_type="audio/wav")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@router.get("/schedules")
def schedules(device=Device):
    with database() as db:
        return [s for s in rows(db, "schedule") if s["device_id"] == device["id"]]


@router.post("/schedules")
def add_schedule(body: Schedule, device=Device):
    return scheduler.create(device["id"], body.model_dump())


@router.post("/schedules/{schedule_id}/pause")
def pause_schedule(schedule_id: uuid.UUID, device=Device):
    with database() as db:
        value = get(db, "schedule", str(schedule_id))
        if not value or value["device_id"] != device["id"]:
            raise HTTPException(404, "Schedule not found")
        value["enabled"] = False
        put(db, "schedule", value["id"], value)
    return value


@router.put("/preferences")
def preferences(body: Preferences, device=Device):
    with database() as db:
        value = get(db, "device", device["id"])
        value.update(body.model_dump(exclude_none=True))
        put(db, "device", value["id"], value)
    return identity.safe_device(value)


@router.get("/swarm")
async def swarm(device=Device):
    from .swarm import swarm_overview
    return await swarm_overview()


@router.get("/coding")
async def coding(device=Device):
    from .coding import coding_overview, decision_inbox
    return {"overview": await coding_overview(), "decisions": await decision_inbox()}


@router.get("/studio")
def studio(device=Device):
    return service.studio_capabilities()


@owner_router.post("/invitations")
def invitation():
    return identity.invite()


@owner_router.get("/devices")
def devices():
    with database() as db:
        return [identity.safe_device(d) for d in rows(db, "device")]


@owner_router.post("/devices/{device_id}/confirm")
def confirm(device_id: uuid.UUID, body: Confirm):
    return identity.set_status(str(device_id), "active", body.fingerprint)


@owner_router.post("/devices/{device_id}/revoke")
def revoke(device_id: uuid.UUID):
    return identity.set_status(str(device_id), "revoked")
