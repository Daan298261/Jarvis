from __future__ import annotations

import base64
import time

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI, HTTPException

from app.mobile import identity, scheduler, store


@pytest.fixture
def mobile_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path


def phone():
    key = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
    return key, public


def signature(key, device):
    challenge = identity.challenge(device["id"])
    message = f'jarvis-mobile-v1\n{device["id"]}\n{challenge["challenge"]}'.encode()
    return base64.b64encode(key.sign(message, ec.ECDSA(hashes.SHA256()))).decode()


def paired():
    key, public = phone()
    invitation = identity.invite()
    device = identity.enroll(invitation["invitation"], public, "Test phone")
    identity.set_status(device["id"], "active", device["fingerprint"])
    return key, device


def test_pairing_requires_owner_and_key_possession(mobile_env):
    key, public = phone()
    invitation = identity.invite()
    device = identity.enroll(invitation["invitation"], public, "Pixel")
    with pytest.raises(HTTPException) as error:
        identity.exchange(device["id"], signature(key, device))
    assert error.value.status_code == 403
    with pytest.raises(HTTPException):
        identity.set_status(device["id"], "active", "0" * 64)
    identity.set_status(device["id"], "active", device["fingerprint"])
    other, _ = phone()
    with pytest.raises(HTTPException):
        identity.exchange(device["id"], signature(other, device))
    proof = signature(key, device)
    assert identity.exchange(device["id"], proof)["access_token"]
    with pytest.raises(HTTPException):
        identity.exchange(device["id"], proof)


def test_copied_invitation_cannot_enroll_second_phone(mobile_env):
    _, public = phone()
    invitation = identity.invite()
    first = identity.enroll(invitation["invitation"], public, "One")
    assert identity.enroll(invitation["invitation"], public, "Retry")["id"] == first["id"]
    _, different = phone()
    with pytest.raises(HTTPException) as error:
        identity.enroll(invitation["invitation"], different, "Stolen")
    assert error.value.status_code == 409


def test_expired_invitation(mobile_env):
    _, public = phone()
    invitation = identity.invite(-1)
    with pytest.raises(HTTPException):
        identity.enroll(invitation["invitation"], public, "Phone")


@pytest.mark.asyncio
async def test_mobile_auth_required_even_on_localhost_and_revoke(mobile_env):
    from app.api.companion import router
    app = FastAPI()
    app.include_router(router)
    key, device = paired()
    session = identity.exchange(device["id"], signature(key, device))
    transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1000))
    async with httpx.AsyncClient(transport=transport, base_url="http://localhost") as client:
        assert (await client.get("/api/companion/models")).status_code == 401
        headers = {"Authorization": "Bearer " + session["access_token"], "X-Jarvis-Device": device["id"]}
        assert (await client.get("/api/companion/models", headers=headers)).status_code == 200
        identity.set_status(device["id"], "revoked")
        assert (await client.get("/api/companion/models", headers=headers)).status_code == 401


def test_daily_schedule_preserves_local_time_across_dst():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    zone = ZoneInfo("Europe/Amsterdam")
    current = datetime(2026, 3, 28, 9, tzinfo=zone).timestamp()
    value = {"recurrence": "daily", "timezone": "Europe/Amsterdam", "next_run": current}
    result = scheduler.next_due(value, current)
    assert datetime.fromtimestamp(result, zone).hour == 9
    assert result - current == 23 * 3600


def test_missed_recurring_runs_coalesce():
    value = {"recurrence": "daily", "timezone": "UTC", "next_run": 86400.0}
    assert scheduler.next_due(value, 4 * 86400 + 1) == 5 * 86400
    assert scheduler.next_due({**value, "recurrence": "once"}, 4 * 86400) is None


@pytest.mark.asyncio
async def test_gateway_does_not_expose_owner_or_desktop_api(mobile_env):
    from app.mobile.gateway import gateway_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway_app()), base_url="https://jarvis") as client:
        for path in ["/api/auth/generate-key", "/api/mobile/manage/devices", "/api/tasks", "/api/companion/%2e%2e/auth/configure"]:
            assert (await client.get(path)).status_code == 404


def test_gateway_pin_survives_certificate_renewal(mobile_env):
    from app.mobile.gateway import server_identity
    first = server_identity(["192.168.1.2"])
    second = server_identity(["192.168.1.2", "jarvis.example.com"])
    assert first["server_pin"] == second["server_pin"]


@pytest.mark.asyncio
async def test_attachments_are_scoped_to_device(mobile_env):
    from app.api.companion import router
    app = FastAPI()
    app.include_router(router)
    key, device = paired()
    otherkey, otherdevice = paired()
    def headers(k, d):
        return {"Authorization": "Bearer " + identity.exchange(d["id"], signature(k, d))["access_token"], "X-Jarvis-Device": d["id"]}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        own = headers(key, device)
        response = await client.post("/api/companion/attachments", content=b"example", headers={**own, "x-filename": "example.txt"})
        assert response.status_code == 200
        url = "/api/companion/attachments/" + response.json()["id"]
        assert (await client.get(url, headers=own)).content == b"example"
        assert (await client.get(url, headers=headers(otherkey, otherdevice))).status_code == 404


@pytest.mark.asyncio
async def test_submission_retry_repairs_crash_without_duplicate_messages(mobile_env, jarvis_env, monkeypatch):
    import uuid
    from app.mobile import service
    from app.db.models import Conversation
    from app.db.session import SessionLocal
    calls = []
    async def create(prompt, **kwargs):
        calls.append(kwargs["request_id"])
        if len(calls) == 1:
            raise RuntimeError("simulated restart after conversation commit")
    monkeypatch.setattr(service.AGENT, "create_task", create)
    request = str(uuid.uuid4())
    with pytest.raises(RuntimeError):
        await service.submit("phone", request, "hello")
    result = await service.submit("phone", request, "hello")
    assert calls[0] == calls[1] == result["task_id"]
    async with SessionLocal() as db:
        conversation = await db.get(Conversation, result["conversation_id"])
        import json
        assert len(json.loads(conversation.messages_json)) == 1
    with pytest.raises(HTTPException) as error:
        await service.submit("phone", request, "different command")
    assert error.value.status_code == 409
