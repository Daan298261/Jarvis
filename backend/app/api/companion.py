from __future__ import annotations

import asyncio
import hashlib
import time
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select

from ..auth import require_owner_private_key, require_owner_private_key_for_pairing
from ..mobile.companion_onboarding import companion_onboarding_snapshot
from ..mobile.pairing_payload import enrich_pairing_session
from ..db.models import Task
from ..db.session import SessionLocal
from ..mobile import identity, realtime_voice, scheduler, service
from ..mobile.store import database, get, put, root, rows

router = APIRouter(prefix="/api/companion", tags=["companion"])
owner_router = APIRouter(prefix="/api/mobile/manage", tags=["mobile management"])
Device = Depends(identity.require_device)


class Enroll(BaseModel):
    code: str | None = Field(default=None, min_length=6, max_length=6, pattern=r"^\d{6}$")
    invitation: str | None = Field(default=None, min_length=20, max_length=100)
    public_key: str = Field(max_length=2000)
    name: str = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def exactly_one_credential(self):
        if bool(self.code) == bool(self.invitation):
            raise ValueError("Provide exactly one of code or invitation")
        return self


class Proof(BaseModel):
    device_id: uuid.UUID
    signature: str = Field(max_length=512)


class Confirm(BaseModel):
    fingerprint: str = Field(min_length=64, max_length=64)


class PairingCodeRequest(BaseModel):
    ttl_minutes: int = Field(default=identity.DEFAULT_PAIRING_TTL_MINUTES,
                             ge=identity.MIN_PAIRING_TTL_MINUTES,
                             le=identity.MAX_PAIRING_TTL_MINUTES)


class CodingDecisionResolution(BaseModel):
    resolution: str = Field(min_length=1, max_length=2000)

    @field_validator("resolution")
    @classmethod
    def require_instructions(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("Resolution instructions are required")
        return value


class Message(BaseModel):
    request_id: uuid.UUID
    text: str = Field(min_length=1, max_length=32000)
    profile: str = "auto"
    conversation_id: uuid.UUID | None = None
    attachments: list[uuid.UUID] = Field(default_factory=list, max_length=10)


class Schedule(BaseModel):
    prompt: str = Field(min_length=1, max_length=32000)
    profile: str = "auto"
    next_run: float = Field(gt=0, lt=253402300799, allow_inf_nan=False)
    timezone: str = "Europe/Amsterdam"
    recurrence: Literal["once", "daily", "weekly"] = "once"


class Preferences(BaseModel):
    notifications: bool | None = None
    critical_calls: bool | None = None
    push_token: str | None = Field(default=None, max_length=4096)
    voice_profile_id: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")


@router.post("/enroll")
def enroll(body: Enroll, request: Request):
    client_ip = request.client.host if request.client else ""
    if body.code:
        return identity.enroll_pairing_code(body.code, body.public_key, body.name, client_ip=client_ip)
    return identity.enroll(body.invitation, body.public_key, body.name, client_ip=client_ip)


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
    voice = voice_status()
    voice["realtime"] = True
    voice["realtime_path"] = "/api/companion/voice/realtime"
    return {"api_version": 1, "device": identity.safe_device(device), "voice": voice,
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


class Approval(BaseModel):
    token: str = Field(min_length=20, max_length=100)
    approved: bool


@router.post("/tasks/{task_id}/approve")
async def approve_task(task_id: uuid.UUID, body: Approval, device=Device):
    return await service.approve(str(task_id), body.token, body.approved)


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
    voice_profile_id: str | None = Field(default=None, min_length=1, max_length=80, pattern=r"^[a-z0-9_]+$")


def _companion_voice_profiles() -> dict:
    from ..voice_profiles.catalog import get_active_voice_profile_id, get_catalog
    active_id = get_active_voice_profile_id()
    profiles = get_catalog().list_profiles(active_id)
    return {
        "active_voice_profile_id": active_id,
        "profiles": [
            {
                "id": profile.id,
                "display_name": profile.display_name,
                "archetype": profile.archetype,
                "available": profile.available,
                "active": profile.active,
                "vram_class": profile.vram_class,
                "unavailable_reason": profile.unavailable_reason,
            }
            for profile in profiles
        ],
    }


@router.get("/voice/profiles")
def voice_profiles(device=Device):
    return _companion_voice_profiles()


@router.post("/voice/profiles/{profile_id}/preview")
async def preview_voice_profile(profile_id: str, device=Device):
    from ..voice_profiles.catalog import get_catalog
    from ..workers.voice import synthesize_speech
    profile = get_catalog().get_available(profile_id)
    if profile is None:
        raise HTTPException(404, "Voice profile is not available")
    try:
        audio = await synthesize_speech(profile.sample_utterance, voice_profile_id=profile.id)
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    return Response(audio, media_type="audio/wav")


@router.post("/voice/speak")
async def speak(body: Speak, device=Device):
    from ..workers.voice import synthesize_speech
    try:
        return Response(await synthesize_speech(body.text, voice_profile_id=body.voice_profile_id), media_type="audio/wav")
    except RuntimeError as exc:
        raise HTTPException(503, str(exc))


@router.websocket("/voice/realtime")
async def voice_realtime(websocket: WebSocket):
    """Duplex conversational voice (RFC-0064). Auth via headers only — never query tokens."""
    device = identity.authenticate_values(
        websocket.headers.get("authorization", ""),
        websocket.headers.get("x-jarvis-device", ""),
    )
    if not device:
        await websocket.close(code=1008, reason="Paired-device authentication required")
        return
    try:
        await realtime_voice.handle_realtime(websocket, device)
    except WebSocketDisconnect:
        return


@router.get("/schedules")
def schedules(device=Device):
    with database() as db:
        return [s for s in rows(db, "schedule") if s["device_id"] == device["id"]]


@router.post("/schedules")
def add_schedule(body: Schedule, device=Device):
    return scheduler.create(device["id"], body.model_dump())


@router.put("/schedules/{schedule_id}")
def update_schedule(schedule_id: uuid.UUID, body: Schedule, device=Device):
    return scheduler.update(device["id"], str(schedule_id), body.model_dump())


@router.post("/schedules/{schedule_id}/pause")
def pause_schedule(schedule_id: uuid.UUID, device=Device):
    with database() as db:
        value = get(db, "schedule", str(schedule_id))
        if not value or value["device_id"] != device["id"]:
            raise HTTPException(404, "Schedule not found")
        value["enabled"] = False
        put(db, "schedule", value["id"], value)
    return value


@router.post("/schedules/{schedule_id}/resume")
def resume_schedule(schedule_id: uuid.UUID, device=Device):
    return scheduler.resume(device["id"], str(schedule_id))


@router.put("/preferences")
def preferences(body: Preferences, device=Device):
    updates = body.model_dump(exclude_none=True)
    voice_profile_id = updates.get("voice_profile_id")
    if voice_profile_id:
        from ..voice_profiles.catalog import get_catalog
        if get_catalog().get_available(voice_profile_id) is None:
            raise HTTPException(409, "Voice profile is not available")
    with database() as db:
        value = get(db, "device", device["id"])
        value.update(updates)
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


@router.post("/coding/decisions/{item_id}/resolve")
def resolve_coding_decision(item_id: str, body: CodingDecisionResolution, device=Device):
    from ..agent.coding_workers import resolve_decision_inbox_item
    from ..agent.worktrees import WorktreeError
    try:
        return resolve_decision_inbox_item(item_id, resolution=body.resolution).as_dict()
    except WorktreeError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/studio")
def studio(device=Device):
    return service.studio_capabilities()


@owner_router.post("/invitations", dependencies=[Depends(require_owner_private_key)])
def invitation():
    return identity.invite()


@owner_router.post("/pairing-codes", dependencies=[Depends(require_owner_private_key_for_pairing)])
def create_pairing_code(body: PairingCodeRequest):
    return enrich_pairing_session(identity.generate_pairing_code(body.ttl_minutes))


@owner_router.post("/pairing-codes/regenerate", dependencies=[Depends(require_owner_private_key_for_pairing)])
def regenerate_pairing_code(body: PairingCodeRequest):
    return enrich_pairing_session(identity.regenerate_pairing_code(body.ttl_minutes))


@owner_router.get("/pairing-codes/status", dependencies=[Depends(require_owner_private_key_for_pairing)])
def pairing_code_status():
    return enrich_pairing_session(identity.pairing_code_status())


@owner_router.get("/devices", dependencies=[Depends(require_owner_private_key)])
def devices():
    with database() as db:
        return [identity.safe_device(d) for d in rows(db, "device")]


@owner_router.post("/devices/{device_id}/confirm", dependencies=[Depends(require_owner_private_key_for_pairing)])
def confirm(device_id: uuid.UUID, body: Confirm):
    return identity.set_status(str(device_id), "active", body.fingerprint)


@owner_router.post("/devices/{device_id}/revoke", dependencies=[Depends(require_owner_private_key)])
def revoke(device_id: uuid.UUID):
    return identity.set_status(str(device_id), "revoked")


class Build(BaseModel):
    endpoint: str = Field(default="", max_length=1024)
    mode: Literal["personalized", "generic"] = "personalized"
    prepare_connection: bool = True
    remote: bool = True


class ConnectionSetup(BaseModel):
    enabled: bool = True
    remote: bool = True


@owner_router.get("/connection", dependencies=[Depends(require_owner_private_key)])
def connection_status():
    from ..mobile.connectivity import CONNECTIVITY
    return CONNECTIVITY.snapshot()


@owner_router.get("/infrastructure", dependencies=[Depends(require_owner_private_key)])
def infrastructure_status():
    from ..mobile.infrastructure import infrastructure_readiness
    return infrastructure_readiness()


@owner_router.post("/connection", dependencies=[Depends(require_owner_private_key)])
async def connection_setup(body: ConnectionSetup):
    from ..mobile.connectivity import CONNECTIVITY
    return await CONNECTIVITY.configure(body.enabled, body.remote)


@router.get("/connection")
def device_connection_status(device=Device):
    from ..mobile.connectivity import CONNECTIVITY
    # Only already-paired devices may discover additional endpoints with this same pin.
    snapshot = CONNECTIVITY.snapshot()
    return {key: snapshot[key] for key in ("endpoints", "server_pin") if key in snapshot}


@owner_router.post("/builds", dependencies=[Depends(require_owner_private_key)])
async def build_apk(body: Build):
    from ..mobile.provision import start
    from ..mobile.connectivity import CONNECTIVITY, origin

    if body.mode == "generic":
        # Full-featured companion APK for releases / sideload; pair in the app after install.
        return await start("", [], generic=True)

    prepared = CONNECTIVITY.snapshot().get("endpoints", [])
    endpoint = body.endpoint or (prepared[0] if prepared else "")
    if not endpoint and body.prepare_connection:
        snapshot = await CONNECTIVITY.configure(True, body.remote)
        prepared = snapshot.get("endpoints", [])
        endpoint = prepared[0] if prepared else ""
    try:
        endpoint = origin(endpoint)
    except ValueError as exc:
        raise HTTPException(
            400,
            "Prepare a connection first, supply an HTTPS gateway origin, or build a generic companion APK.",
        ) from exc
    return await start(endpoint, prepared if endpoint in prepared else [], generic=False)


@owner_router.get("/builds/{job_id}", dependencies=[Depends(require_owner_private_key)])
def build_status(job_id: uuid.UUID):
    from ..mobile.provision import job
    return job(str(job_id))


@owner_router.get("/builds/{job_id}/apk", dependencies=[Depends(require_owner_private_key)])
def apk_download(job_id: uuid.UUID):
    from ..mobile.provision import job
    value = job(str(job_id))
    if value["state"] != "completed":
        raise HTTPException(409, "APK is not ready")
    result = value.get("result") or {}
    filename = result.get("filename") or "JarvisCompanion.apk"
    path = root() / "builds" / filename
    download_name = filename if filename.endswith(".apk") else "JarvisCompanion.apk"
    return FileResponse(path, filename=download_name, media_type="application/vnd.android.package-archive")



@router.get("/whatsapp/contact")
async def whatsapp_contact(device=Device):
    """Return a Jarvis WhatsApp contact card for the companion to save."""
    from ..integrations.setup import WHATSAPP_PAIRING
    from ..integrations.whatsapp_bridge import jarvis_whatsapp_contact

    status = WHATSAPP_PAIRING.status()
    if not bool(status.get("paired") or status.get("state") == "connected"):
        return {
            "available": False,
            "reason": "WhatsApp is not connected on the Jarvis desktop. Connect it in Setup first.",
        }
    try:
        return await jarvis_whatsapp_contact()
    except HTTPException as exc:
        if exc.status_code in {400, 502, 504}:
            return {"available": False, "reason": str(exc.detail)}
        raise


class ApkSendRequest(BaseModel):
    to: str | None = Field(default=None, max_length=254)


@owner_router.post("/builds/{job_id}/send/{channel}", dependencies=[Depends(require_owner_private_key)])
async def send_apk(job_id: uuid.UUID, channel: Literal["email", "whatsapp"], body: ApkSendRequest | None = None):
    from ..mobile.apk_delivery import send_apk_email, send_apk_whatsapp

    payload = body or ApkSendRequest()
    if channel == "email":
        return send_apk_email(str(job_id), payload.to)
    return await send_apk_whatsapp(str(job_id), payload.to)

class Contact(BaseModel):
    incident_id: uuid.UUID
    task_id: uuid.UUID | None = None


@owner_router.post("/devices/{device_id}/call", dependencies=[Depends(require_owner_private_key)])
async def contact(device_id: uuid.UUID, body: Contact):
    from ..mobile.calls import create_call
    from ..mobile.runtime import deliver_one, enqueue_push
    call = create_call(str(device_id), "incoming", task_id=str(body.task_id) if body.task_id else None, incident_id=str(body.incident_id))
    with database() as db:
        device = get(db, "device", str(device_id))
    queued = enqueue_push(device, call["id"], "call", call["expires_at"])
    delivered = await deliver_one(queued)
    return {**call, "push_delivered": delivered}
