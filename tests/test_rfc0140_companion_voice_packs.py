"""RFC-0140 companion on-device voice pack catalog, cache, and routing tests."""

from __future__ import annotations

import base64
import hashlib
from pathlib import Path

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
    device = identity.enroll(invitation["invitation"], public, "Voice phone")
    identity.set_status(device["id"], "active", device["fingerprint"])
    token = identity.exchange(device["id"], _signature(key, device))["access_token"]
    headers = {"Authorization": f"Bearer {token}", "X-Jarvis-Device": device["id"]}
    return device, headers


def test_voice_pack_catalog_urls_non_empty():
    from app.mobile import companion_voice_packs

    companion_voice_packs.validate_catalog_urls()
    for pack in companion_voice_packs.COMPANION_VOICE_PACK_CATALOG:
        assert pack["url"].startswith("https://")
        assert pack["sha256"] and set(pack["sha256"]) != {"0"}
        assert len(pack["sha256"]) == 64
        assert pack["size_bytes"] > 0
        assert pack["role"] in {"stt", "tts"}
        for art in companion_voice_packs.pack_artifacts(pack):
            assert art["url"].startswith("https://")
            assert len(art["sha256"]) == 64


def test_voice_pack_catalog_empty_url_is_fail(monkeypatch):
    from app.mobile import companion_voice_packs

    broken = dict(companion_voice_packs.COMPANION_VOICE_PACK_CATALOG[0])
    broken["url"] = ""
    broken["artifacts"] = [{**broken["artifacts"][0], "url": ""}]
    monkeypatch.setattr(
        companion_voice_packs,
        "COMPANION_VOICE_PACK_CATALOG",
        [broken, *companion_voice_packs.COMPANION_VOICE_PACK_CATALOG[1:]],
    )
    with pytest.raises(ValueError, match="empty url"):
        companion_voice_packs.validate_catalog_urls()


def test_voice_pack_hash_fail_not_ready(mobile_env, monkeypatch):
    from app.mobile import companion_voice_packs

    monkeypatch.setattr(companion_voice_packs, "data_dir", lambda: mobile_env)
    pack = dict(companion_voice_packs.voice_pack_by_id("whisper-tiny-en-cpp") or {})
    target = companion_voice_packs.artifact_cache_path(pack, companion_voice_packs.pack_artifacts(pack)[0])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"corrupt-voice-pack-bytes")
    assert companion_voice_packs._cache_ready(pack) is False
    status = companion_voice_packs.leader_voice_cache_status(pack["id"])
    assert status["state"] != "ready"


def test_voice_pack_hash_ok_ready(mobile_env, monkeypatch):
    from app.mobile import companion_voice_packs

    monkeypatch.setattr(companion_voice_packs, "data_dir", lambda: mobile_env)
    pack = dict(companion_voice_packs.voice_pack_by_id("whisper-tiny-en-cpp") or {})
    art = companion_voice_packs.pack_artifacts(pack)[0]
    target = companion_voice_packs.artifact_cache_path(pack, art)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = b"verified-whisper-tiny"
    target.write_bytes(payload)
    art = dict(art)
    art["sha256"] = hashlib.sha256(payload).hexdigest()
    pack["artifacts"] = [art]
    pack["sha256"] = art["sha256"]
    assert companion_voice_packs._cache_ready(pack) is True


@pytest.mark.asyncio
async def test_voice_packs_api_catalog(mobile_env):
    from app.api.companion import router

    app = FastAPI()
    app.include_router(router)
    _, headers = _paired()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/companion/voice-packs", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["packs"]
    ids = {p["id"] for p in body["packs"]}
    assert "whisper-tiny-en-cpp" in ids
    assert "whisper-base-en-cpp" in ids
    assert "pocket-tts-en" in ids
    assert "piper-en-lessac-medium" in ids
    for pack in body["packs"]:
        assert pack["url"].startswith("https://")
        assert pack["sha256"]
        assert "leader_cache" in pack
    stt_rec = next(p for p in body["packs"] if p["id"] == "whisper-tiny-en-cpp")
    tts_rec = next(p for p in body["packs"] if p["id"] == "pocket-tts-en")
    assert stt_rec["recommended"] is True
    assert tts_rec["recommended"] is True
    assert body["recommended_combined_bytes"] <= body["auto_download_hard_cap_bytes"]
    assert stt_rec["size_bytes"] <= 80_000_000
    assert tts_rec["size_bytes"] <= 150_000_000


@pytest.mark.asyncio
async def test_voice_pack_file_requires_cache(mobile_env):
    from app.api.companion import router

    app = FastAPI()
    app.include_router(router)
    _, headers = _paired()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/companion/voice-packs/whisper-tiny-en-cpp/file", headers=headers)
    assert response.status_code == 409


def test_voice_routing_preference_table():
    """Mirror Android CompanionVoiceRouting preference rules (RFC-0140 §5)."""
    from app.mobile.companion_voice_routing import decide_voice_route

    # Leader + healthy realtime → gateway/host
    d = decide_voice_route(
        leader_reachable=True,
        realtime_voice_healthy=True,
        host_tts_healthy=True,
        stt_pack_status="ready",
        tts_pack_status="ready",
    )
    assert d["stt"] == "gateway"
    assert d["tts"] == "host_neural"
    assert d["banner"] is None

    # Leader reachable but voice failing → offer on-device with banner
    d = decide_voice_route(
        leader_reachable=True,
        realtime_voice_healthy=False,
        host_tts_healthy=False,
        stt_pack_status="ready",
        tts_pack_status="ready",
    )
    assert d["stt"] == "on_device"
    assert d["tts"] == "on_device"
    assert d["banner"]

    # Leader unreachable + packs ready → on-device required
    d = decide_voice_route(
        leader_reachable=False,
        realtime_voice_healthy=False,
        host_tts_healthy=False,
        stt_pack_status="ready",
        tts_pack_status="ready",
        local_llm_ready=True,
    )
    assert d["mode"] == "B"
    assert d["stt"] == "on_device"
    assert d["tts"] == "on_device"

    # Leader unreachable + packs missing → install, never pretend
    d = decide_voice_route(
        leader_reachable=False,
        realtime_voice_healthy=False,
        host_tts_healthy=False,
        stt_pack_status="missing",
        tts_pack_status="missing",
    )
    assert d["stt"] == "install"
    assert d["tts"] == "install"
    assert d["error"]

    # Online must not silent-replace host neural when healthy
    d = decide_voice_route(
        leader_reachable=True,
        realtime_voice_healthy=True,
        host_tts_healthy=True,
        stt_pack_status="running",
        tts_pack_status="running",
        prefer_on_device_frontend=False,
    )
    assert d["tts"] == "host_neural"
    assert d["stt"] == "gateway"
