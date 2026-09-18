from __future__ import annotations

import base64
import uuid

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.mobile import identity, store


@pytest.fixture
def mobile_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return tmp_path


def _phone():
    key = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    ).decode()
    return key, public


def _signature(key, device):
    challenge = identity.challenge(device["id"])
    message = f'jarvis-mobile-v1\n{device["id"]}\n{challenge["challenge"]}'.encode()
    return base64.b64encode(key.sign(message, ec.ECDSA(hashes.SHA256()))).decode()


def _paired():
    key, public = _phone()
    invitation = identity.invite()
    device = identity.enroll(invitation["invitation"], public, "Offline phone")
    identity.set_status(device["id"], "active", device["fingerprint"])
    token = identity.exchange(device["id"], _signature(key, device))["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Jarvis-Device": device["id"]}
    return device, headers


@pytest.mark.asyncio
async def test_model_pack_catalog_metadata_only(mobile_env):
    from app.api.companion import router

    app = FastAPI()
    app.include_router(router)
    _, headers = _paired()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/companion/model-packs", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["engine"] == "llama.cpp"
    assert body["packs"]
    assert "gguf" in body["packs"][0]["filename"].lower()
    assert all("url" in pack for pack in body["packs"])


@pytest.mark.asyncio
async def test_offline_turn_sync_labels_device_local_draft(mobile_env, jarvis_env):
    from app.api.companion import router
    from app.db.models import Conversation
    from app.db.session import SessionLocal

    app = FastAPI()
    app.include_router(router)
    device, headers = _paired()
    user_id = str(uuid.uuid4())
    assistant_id = str(uuid.uuid4())
    payload = {
        "turns": [
            {
                "request_id": user_id,
                "client_message_id": user_id,
                "role": "user",
                "text": "What is on my calendar?",
                "origin": "device_offline",
            },
            {
                "request_id": assistant_id,
                "client_message_id": assistant_id,
                "role": "assistant",
                "text": "I only have the last synced snapshot; connect to Jarvis for live calendar tools.",
                "origin": "device_local_draft",
            },
        ]
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/companion/sync/offline-turns", headers=headers, json=payload)
    assert response.status_code == 200
    cid = response.json()["conversation_id"]
    async with SessionLocal() as db:
        conversation = await db.get(Conversation, cid)
        messages = __import__("json").loads(conversation.messages_json)
    assert len(messages) == 2
    assert messages[0]["origin"] == "device_offline"
    assert messages[1]["origin"] == "device_local_draft"
    assert messages[1]["pending_leader_acceptance"] is True
    assert messages[0]["device_id"] == device["id"]


@pytest.mark.asyncio
async def test_offline_sync_idempotent_by_client_message_id(mobile_env, jarvis_env):
    from app.api.companion import router

    app = FastAPI()
    app.include_router(router)
    _, headers = _paired()
    turn_id = str(uuid.uuid4())
    payload = {
        "conversation_id": str(uuid.uuid4()),
        "turns": [
            {
                "request_id": turn_id,
                "client_message_id": turn_id,
                "role": "user",
                "text": "Ping",
                "origin": "device_offline",
            }
        ],
    }
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/companion/sync/offline-turns", headers=headers, json=payload)
        second = await client.post("/api/companion/sync/offline-turns", headers=headers, json=payload)
    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["appended"] == 0
