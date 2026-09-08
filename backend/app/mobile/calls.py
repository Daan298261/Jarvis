"""Device-bound WebRTC calls; media stays in memory on the Jarvis node."""
from __future__ import annotations

import asyncio
import importlib.util
import io
import json
import os
import time
import uuid
import wave
from fractions import Fraction

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .identity import require_device
from .store import database, get, put, rows

router = APIRouter(prefix="/api/companion/calls", tags=["mobile calls"])
PEERS: dict[str, object] = {}
ACTIVE_STATES = {"ringing", "connecting", "active"}


def capabilities():
    available = importlib.util.find_spec("aiortc") is not None
    return {"available": available, "push_configured": bool(os.environ.get("JARVIS_PUSH_URL")),
            "turn_configured": bool(os.environ.get("JARVIS_TURN_URL")),
            "detail": "WebRTC available" if available else "Install backend/requirements-mobile.txt to enable calls"}


def ice_servers():
    url = os.environ.get("JARVIS_TURN_URL")
    if not url:
        return []
    import base64
    import hashlib
    import hmac
    secret = os.environ.get("JARVIS_TURN_SECRET", "")
    if not secret:
        return []
    username = str(int(time.time()) + 600)
    credential = base64.b64encode(hmac.new(secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
    return [{"urls": [url], "username": username, "credential": credential}]


def update(call_id: str, **values):
    with database() as db:
        call = get(db, "call", call_id)
        if call:
            call.update(values, updated_at=time.time())
            put(db, "call", call_id, call)
    return call


def owned(call_id: str, device_id: str):
    with database() as db:
        call = get(db, "call", call_id)
    if not call or call["device_id"] != device_id:
        raise HTTPException(404, "Call not found")
    if call["state"] == "ringing" and call["expires_at"] < time.time():
        call = update(call_id, state="missed")
    return call


def create_call(device_id: str, direction: str, conversation_id: str | None = None,
                task_id: str | None = None, incident_id: str | None = None):
    if not capabilities()["available"]:
        raise HTTPException(503, "WebRTC dependencies are not installed")
    with database() as db:
        device = get(db, "device", device_id)
        if not device or device["status"] != "active":
            raise HTTPException(401, "Device revoked")
        if direction == "incoming" and not device.get("critical_calls"):
            raise HTTPException(409, "Incoming critical calls are disabled for this device")
        for prior in rows(db, "call"):
            if prior["device_id"] == device_id:
                if incident_id and prior.get("incident_id") == incident_id:
                    return prior
                if direction == "incoming" and time.time() - prior["created_at"] < 60:
                    raise HTTPException(429, "Wait one minute before calling this device again")
                if prior["state"] in ACTIVE_STATES and prior["expires_at"] > time.time():
                    raise HTTPException(409, "A call is already in progress")
        call = {"id": str(uuid.uuid4()), "device_id": device_id, "direction": direction,
                "state": "ringing", "conversation_id": conversation_id, "task_id": task_id,
                "incident_id": incident_id, "created_at": time.time(), "updated_at": time.time(),
                "expires_at": time.time() + 45}
        put(db, "call", call["id"], call)
    return call


class Start(BaseModel):
    conversation_id: uuid.UUID | None = None


class Offer(BaseModel):
    sdp: str = Field(min_length=10, max_length=64000)
    type: str = "offer"


@router.get("")
def history(device=Depends(require_device)):
    with database() as db:
        items = [c for c in rows(db, "call") if c["device_id"] == device["id"]]
    return [owned(c["id"], device["id"]) for c in sorted(items, key=lambda c: c["created_at"], reverse=True)[:50]]


@router.post("")
def start(body: Start, device=Depends(require_device)):
    result = create_call(device["id"], "outgoing", str(body.conversation_id) if body.conversation_id else None)
    return {**result, "ice_servers": ice_servers()}


@router.get("/{call_id}")
def detail(call_id: uuid.UUID, device=Depends(require_device)):
    return {**owned(str(call_id), device["id"]), "ice_servers": ice_servers()}


@router.post("/{call_id}/end")
async def end(call_id: uuid.UUID, device=Depends(require_device)):
    call = owned(str(call_id), device["id"])
    peer = PEERS.pop(call["id"], None)
    if peer:
        await peer.close()
    return update(call["id"], state="ended", ended_at=time.time())


@router.post("/{call_id}/offer")
async def offer(call_id: uuid.UUID, body: Offer, device=Depends(require_device)):
    call = owned(str(call_id), device["id"])
    if call["state"] not in ACTIVE_STATES or body.type != "offer":
        raise HTTPException(409, "Call offer is no longer valid")
    if call["id"] in PEERS:
        raise HTTPException(409, "Call already connected; reconnect using a new call")
    from aiortc import RTCPeerConnection, RTCSessionDescription, RTCConfiguration, RTCIceServer
    from .media import VoiceBridge
    config = RTCConfiguration(iceServers=[RTCIceServer(**entry) for entry in ice_servers()])
    peer = RTCPeerConnection(config)
    PEERS[call["id"]] = peer
    bridge = VoiceBridge(call)
    peer.addTrack(bridge.output)
    update(call["id"], state="connecting", expires_at=time.time() + 3600)

    @peer.on("track")
    def on_track(track):
        if track.kind == "audio":
            bridge.start(track)

    @peer.on("connectionstatechange")
    async def state_changed():
        if peer.connectionState == "connected":
            update(call["id"], state="active")
        elif peer.connectionState in {"failed", "closed"}:
            bridge.stop()
            PEERS.pop(call["id"], None)
            update(call["id"], state="ended" if peer.connectionState == "closed" else "failed")

    try:
        await peer.setRemoteDescription(RTCSessionDescription(sdp=body.sdp, type="offer"))
        await peer.setLocalDescription(await peer.createAnswer())
        return {"sdp": peer.localDescription.sdp, "type": peer.localDescription.type}
    except Exception:
        await peer.close()
        PEERS.pop(call["id"], None)
        update(call["id"], state="failed")
        raise HTTPException(400, "Unable to establish WebRTC media")
