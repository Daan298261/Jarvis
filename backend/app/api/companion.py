from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field, model_validator

from ..auth import require_owner_private_key
from ..mobile import identity
from ..mobile.store import database, rows

router = APIRouter(prefix="/api/companion", tags=["companion"])
owner_router = APIRouter(
    prefix="/api/mobile/manage",
    dependencies=[Depends(require_owner_private_key)],
    tags=["mobile management"],
)


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


class Confirm(BaseModel):
    fingerprint: str = Field(min_length=64, max_length=64)


class PairingCodeRequest(BaseModel):
    ttl_minutes: int = Field(default=identity.DEFAULT_PAIRING_TTL_MINUTES, ge=identity.MIN_PAIRING_TTL_MINUTES, le=identity.MAX_PAIRING_TTL_MINUTES)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return ""


@router.post("/enroll")
def enroll(body: Enroll, request: Request):
    client_ip = _client_ip(request)
    if body.code:
        return identity.enroll_pairing_code(body.code, body.public_key, body.name, client_ip=client_ip)
    return identity.enroll(body.invitation, body.public_key, body.name, client_ip=client_ip)


@owner_router.post("/pairing-codes")
def create_pairing_code(body: PairingCodeRequest):
    return identity.generate_pairing_code(body.ttl_minutes)


@owner_router.post("/pairing-codes/regenerate")
def regenerate_pairing_code(body: PairingCodeRequest):
    return identity.regenerate_pairing_code(body.ttl_minutes)


@owner_router.get("/pairing-codes/status")
def pairing_code_status():
    return identity.pairing_code_status()


@owner_router.post("/invitations")
def invitation():
    return identity.invite()


@owner_router.get("/devices")
def devices():
    with database() as db:
        return [identity.safe_device(device) for device in rows(db, "device")]


@owner_router.post("/devices/{device_id}/confirm")
def confirm(device_id: uuid.UUID, body: Confirm):
    return identity.set_status(str(device_id), "active", body.fingerprint)


@owner_router.post("/devices/{device_id}/revoke")
def revoke(device_id: uuid.UUID):
    return identity.set_status(str(device_id), "revoked")
