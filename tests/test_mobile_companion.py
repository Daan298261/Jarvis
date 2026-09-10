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


@pytest.mark.asyncio
async def test_mobile_approval_is_single_use_and_bound_to_current_action(mobile_env, jarvis_env):
    from app.mobile import service
    from app.db.models import Task
    from app.db.session import SessionLocal
    async with SessionLocal() as db:
        db.add(Task(id="approval-test", title="Test", prompt="Test", status="waiting", waiting_for_confirmation=True,
                    confirmation_payload='{"tool":"file","path":"first"}'))
        await db.commit()
    first = (await service.task_snapshot("approval-test"))["approval"]
    async with SessionLocal() as db:
        task = await db.get(Task, "approval-test")
        task.confirmation_payload = '{"tool":"file","path":"second"}'
        await db.commit()
    with pytest.raises(HTTPException) as error:
        await service.approve("approval-test", first["token"], True)
    assert error.value.status_code == 409
    second = (await service.task_snapshot("approval-test"))["approval"]
    assert second["token"] != first["token"]
    assert (await service.approve("approval-test", second["token"], False))["status"] == "cancelled"
    with pytest.raises(HTTPException) as error:
        await service.approve("approval-test", second["token"], True)
    assert error.value.status_code == 409


@pytest.mark.asyncio
async def test_agent_approval_compare_and_swap_rejects_racing_change(mobile_env, jarvis_env):
    from app.agent.loop import AGENT
    from app.db.models import Task
    from app.db.session import SessionLocal
    async with SessionLocal() as db:
        db.add(Task(id="approval-race", title="Test", prompt="Test", waiting_for_confirmation=True, confirmation_payload='{"new":true}'))
        await db.commit()
    with pytest.raises(ValueError):
        await AGENT.confirm_task("approval-race", True, expected_payload='{"old":true}')
    async with SessionLocal() as db:
        task = await db.get(Task, "approval-race")
        assert task.waiting_for_confirmation
        assert task.confirmation_payload == '{"new":true}'


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


@pytest.mark.asyncio
async def test_mobile_can_resolve_coding_decision_with_explicit_instructions(mobile_env, monkeypatch):
    from app.agent import coding_workers
    from app.api.companion import router
    app = FastAPI()
    app.include_router(router)
    key, device = paired()
    session = identity.exchange(device["id"], signature(key, device))
    headers = {"Authorization": "Bearer " + session["access_token"], "X-Jarvis-Device": device["id"]}
    received = {}

    class Resolved:
        def as_dict(self):
            return {"id": "decision-1", "status": "resolved", "resolution": received["resolution"]}

    def resolve(item_id, resolution):
        received.update(item_id=item_id, resolution=resolution)
        return Resolved()

    monkeypatch.setattr(coding_workers, "resolve_decision_inbox_item", resolve)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost") as client:
        url = "/api/companion/coding/decisions/decision-1/resolve"
        assert (await client.post(url, json={"resolution": "keep the verified branch"})).status_code == 401
        empty = await client.post(url, json={"resolution": ""}, headers=headers)
        assert empty.status_code == 422
        response = await client.post(url, json={"resolution": "keep the verified branch"}, headers=headers)
    assert response.status_code == 200
    assert response.json()["status"] == "resolved"
    assert received == {"item_id": "decision-1", "resolution": "keep the verified branch"}


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


def test_schedule_edit_and_resume_are_device_scoped(mobile_env):
    original = scheduler.create("phone-one", {"prompt": "first", "profile": "auto", "next_run": 100.0,
                                               "timezone": "UTC", "recurrence": "daily"})
    changed = scheduler.update("phone-one", original["id"], {"prompt": "second", "profile": "auto",
                                "next_run": 200.0, "timezone": "UTC", "recurrence": "weekly"})
    assert changed["prompt"] == "second" and changed["enabled"]
    with pytest.raises(HTTPException) as error:
        scheduler.update("phone-two", original["id"], {"prompt": "stolen", "profile": "auto",
                         "next_run": 300.0, "timezone": "UTC", "recurrence": "once"})
    assert error.value.status_code == 404
    with store.database() as db:
        saved = store.get(db, "schedule", original["id"])
        saved["enabled"] = False
        store.put(db, "schedule", original["id"], saved)
    resumed = scheduler.resume("phone-one", original["id"], now=500.0)
    assert resumed["enabled"] and resumed["next_run"] > 500.0


def test_past_one_time_schedule_requires_edit_before_resume(mobile_env):
    value = scheduler.create("phone", {"prompt": "once", "profile": "auto", "next_run": 100.0,
                                        "timezone": "UTC", "recurrence": "once"})
    with pytest.raises(HTTPException) as error:
        scheduler.resume("phone", value["id"], now=101.0)
    assert error.value.status_code == 409


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
