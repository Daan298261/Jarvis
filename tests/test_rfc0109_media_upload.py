from __future__ import annotations

import base64
import uuid

import httpx
import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import FastAPI

from app.mobile import identity, store


@pytest.fixture
def media_env(tmp_path, monkeypatch):
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.media.store.data_dir", lambda: tmp_path)
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    return tmp_path


@pytest.fixture
def media_app(allow_loopback_api):
    from app.auth import require_owner_private_key
    from app.main import app

    app.dependency_overrides[require_owner_private_key] = lambda: None
    yield app
    app.dependency_overrides.pop(require_owner_private_key, None)


def _phone():
    key = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    ).decode()
    return key, public


def _device_headers():
    key, public = _phone()
    invitation = identity.invite()
    device = identity.enroll(invitation["invitation"], public, "RFC-0109 phone")
    identity.set_status(device["id"], "active", device["fingerprint"])
    token = identity.exchange(device["id"], _signature(key, device))["access_token"]
    return device, {
        "Authorization": f"Bearer {token}",
        "X-Jarvis-Device": device["id"],
    }


def _signature(key, device):
    challenge = identity.challenge(device["id"])
    message = f'jarvis-mobile-v1\n{device["id"]}\n{challenge["challenge"]}'.encode()
    return base64.b64encode(key.sign(message, ec.ECDSA(hashes.SHA256()))).decode()


@pytest.mark.asyncio
async def test_desktop_upload_rejects_empty(media_env, media_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=media_app), base_url="http://test") as client:
        response = await client.post("/api/media/uploads", content=b"")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_image_cap_returns_413(media_env, media_app):
    from app.media.store import caps_for_kind
    cap = caps_for_kind("image")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=media_app), base_url="http://test") as client:
        response = await client.post(
            "/api/media/uploads",
            content=b"x" * (cap + 1),
            headers={"x-filename": "big.png", "content-type": "image/png", "x-jarvis-upload-kind": "image"},
        )
    assert response.status_code == 413


@pytest.mark.asyncio
async def test_chunk_assemble_video(media_env, media_app):
    upload_id = str(uuid.uuid4())
    payload = b"part-a" + b"part-b"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=media_app), base_url="http://test") as client:
        first = await client.post(
            "/api/media/uploads",
            content=payload[:6],
            headers={
                "x-filename": "clip.mp4",
                "content-type": "video/mp4",
                "x-jarvis-upload-id": upload_id,
                "x-jarvis-chunk-index": "0",
                "x-jarvis-chunk-total": "2",
                "x-jarvis-upload-kind": "video",
            },
        )
        assert first.status_code == 200
        assert first.json()["complete"] is False
        second = await client.post(
            "/api/media/uploads",
            content=payload[6:],
            headers={
                "x-filename": "clip.mp4",
                "content-type": "video/mp4",
                "x-jarvis-upload-id": upload_id,
                "x-jarvis-chunk-index": "1",
                "x-jarvis-chunk-total": "2",
                "x-jarvis-upload-kind": "video",
            },
        )
        assert second.status_code == 200
        body = second.json()
        assert body["kind"] == "video"
        assert body["size"] == len(payload)
        download = await client.get(f"/api/media/uploads/{body['id']}/download")
        assert download.content == payload


@pytest.mark.asyncio
async def test_companion_device_isolation(media_env):
    from app.api.companion import router

    app = FastAPI()
    app.include_router(router)
    device_a, headers_a = _device_headers()
    device_b, headers_b = _device_headers()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        created = await client.post(
            "/api/companion/attachments",
            content=b"secret",
            headers={**headers_a, "x-filename": "a.txt", "x-jarvis-upload-kind": "file"},
        )
        assert created.status_code == 200
        upload_id = created.json()["id"]
        ok = await client.get(f"/api/companion/attachments/{upload_id}", headers=headers_a)
        assert ok.content == b"secret"
        denied = await client.get(f"/api/companion/attachments/{upload_id}", headers=headers_b)
        assert denied.status_code == 404


@pytest.mark.asyncio
async def test_analyze_ocr_limitation_without_engine(media_env, media_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=media_app), base_url="http://test") as client:
        created = await client.post(
            "/api/media/uploads",
            content=b"\x89PNG\r\n\x1a\n",
            headers={"x-filename": "scan.png", "content-type": "image/png", "x-jarvis-upload-kind": "image"},
        )
        upload_id = created.json()["id"]
        analyzed = await client.post(f"/api/media/uploads/{upload_id}/analyze", json={"actions": ["ocr"]})
        assert analyzed.status_code == 200
        ocr = analyzed.json()["actions"]["ocr"]
        assert ocr["status"] == "unavailable"
        assert ocr.get("limitation")


@pytest.mark.asyncio
async def test_studio_honest_when_not_connected(media_env, media_app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=media_app), base_url="http://test") as client:
        created = await client.post(
            "/api/media/uploads",
            content=b"hello",
            headers={"x-filename": "note.txt", "content-type": "text/plain", "x-jarvis-upload-kind": "file"},
        )
        upload_id = created.json()["id"]
        studio = await client.post(f"/api/media/uploads/{upload_id}/studio", json={})
        assert studio.status_code == 503
        assert "not connected" in studio.json()["detail"].lower()
