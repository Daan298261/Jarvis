from __future__ import annotations

import base64
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.mobile import identity, store


@pytest.fixture
def mobile_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.mobile.companion_offline.data_dir", lambda: tmp_path)
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
    for pack in body["packs"]:
        assert pack["url"].startswith("https://")
        assert pack["sha256"] and set(pack["sha256"]) != {"0"}
        assert pack["size_bytes"] > 0
        assert "leader_cache" in pack
    recommended = next(p for p in body["packs"] if p["recommended"])
    assert recommended["id"] == "qwen3-1.7b-abliterated-q4"
    assert sum(1 for p in body["packs"] if p["recommended"]) == 1
    opt_in = next(p for p in body["packs"] if p["id"] == "qwen3.5-4b-abliterated-q4")
    assert opt_in["recommended"] is False and opt_in["min_ram_mb"] > recommended["min_ram_mb"]
    for pack in body["packs"]:
        if pack["id"].startswith("qwen3.5"):
            # Pinned to an immutable HF commit, never the moving main branch.
            assert "/resolve/main/" not in pack["url"]
    assert body["leader_pack_cache"]["pack_id"] == recommended["id"]
    assert body["leader_pack_cache"]["state"] in {"idle", "downloading", "ready", "error"}


@pytest.mark.asyncio
async def test_leader_pack_cache_ready_when_hash_matches(mobile_env, monkeypatch):
    from app.mobile import companion_offline

    pack = dict(companion_offline.pack_by_id("qwen2.5-1.5b-instruct-q4") or {})
    target = companion_offline.pack_cache_path(pack)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"cached-pack-bytes")
    pack["sha256"] = companion_offline._sha256_file(target)
    pack["size_bytes"] = target.stat().st_size
    monkeypatch.setattr(companion_offline, "COMPANION_PACK_CATALOG", [
        pack if entry["id"] == pack["id"] else entry
        for entry in companion_offline.COMPANION_PACK_CATALOG
    ])
    assert companion_offline._cache_ready(pack) is False
    import asyncio
    assert await asyncio.to_thread(companion_offline._verify_and_mark, target, pack["sha256"])

    def unexpected_hash(_path):
        raise AssertionError("Pack status polling must not hash model weights")

    monkeypatch.setattr(companion_offline, "_sha256_file", unexpected_hash)
    status = companion_offline.leader_cache_status(pack["id"])
    assert status["state"] == "ready"
    assert status["bytes_done"] == pack["size_bytes"]
    target.unlink(missing_ok=True)


async def test_companion_pack_download_honors_internet_deny(mobile_env, monkeypatch):
    from app.mobile import companion_offline
    from app.policy.computer_permissions import apply_grant, reset_computer_permission_state

    monkeypatch.setattr("app.policy.computer_permissions.data_dir", lambda: mobile_env)
    monkeypatch.setattr(companion_offline, "data_dir", lambda: mobile_env)
    reset_computer_permission_state()
    apply_grant("network.internet", "deny")
    companion_offline._CACHE.update(state="idle", pack_id="", bytes_done=0, size_bytes=0, last_error="")
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        return httpx.Response(200, content=b"gguf-bytes")

    class Client(httpx.AsyncClient):
        def __init__(self, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handler)
            super().__init__(**kwargs)

    monkeypatch.setattr("app.policy.network_http.httpx.AsyncClient", Client)
    await companion_offline._download_recommended()
    assert seen["n"] == 0
    assert companion_offline._CACHE["state"] == "error"
    err = (companion_offline._CACHE.get("last_error") or "").lower()
    assert "permission" in err or "internet" in err or "don't allow" in err or "not allow" in err


@pytest.mark.asyncio
async def test_model_pack_file_requires_cache(mobile_env):
    from app.api.companion import router

    app = FastAPI()
    app.include_router(router)
    _, headers = _paired()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/companion/model-packs/qwen2.5-1.5b-instruct-q4/file", headers=headers)
    assert response.status_code == 409


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


@pytest.mark.asyncio
async def test_offline_sync_retry_into_client_thread_after_lost_reply(mobile_env, jarvis_env):
    """Phone mints the thread id before posting; a lost reply plus a new turn must not fork or duplicate."""
    import json

    from app.api.companion import router
    from app.db.models import Conversation
    from app.db.session import SessionLocal

    app = FastAPI()
    app.include_router(router)
    _, headers = _paired()
    thread = str(uuid.uuid4())
    ids = [str(uuid.uuid4()) for _ in range(3)]

    def turn(i, role="user"):
        return {
            "request_id": ids[i],
            "client_message_id": ids[i],
            "role": role,
            "text": f"turn {i}",
            "origin": "device_offline" if role == "user" else "device_local_draft",
        }

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post(
            "/api/companion/sync/offline-turns",
            headers=headers,
            json={"conversation_id": thread, "turns": [turn(0), turn(1, "assistant")]},
        )
        # Reply "lost": the phone retries the same turns plus a new one into the same thread.
        retry = await client.post(
            "/api/companion/sync/offline-turns",
            headers=headers,
            json={"conversation_id": thread, "turns": [turn(0), turn(1, "assistant"), turn(2)]},
        )
    assert first.status_code == 200 and retry.status_code == 200
    assert first.json()["conversation_id"] == thread == retry.json()["conversation_id"]
    assert first.json()["appended"] == 2 and retry.json()["appended"] == 1
    async with SessionLocal() as db:
        conversation = await db.get(Conversation, thread)
        messages = json.loads(conversation.messages_json)
    assert [m["id"] for m in messages] == ids
