from __future__ import annotations

import base64

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.mobile import identity
from app.mobile.lan_beacon import encode_beacon, parse_beacon, public_beacon_payload

from tests.test_companion_pairing import companion_env, owner_headers, phone_keypair


def _signature(key, device):
    challenge = identity.challenge(device["id"])
    message = f'jarvis-mobile-v1\n{device["id"]}\n{challenge["challenge"]}'.encode()
    return base64.b64encode(key.sign(message, ec.ECDSA(hashes.SHA256()))).decode()


def test_beacon_round_trip_rejects_probes_and_bad_pins():
    payload = {
        "https": "https://192.168.1.12:4781",
        "server_pin": "a" * 64,
        "name": "Jarvis",
    }
    parsed = parse_beacon(encode_beacon(payload))
    assert parsed["service"] == "jarvis-companion"
    assert parsed["https"] == payload["https"]
    assert parsed["server_pin"] == "a" * 64
    assert parse_beacon(b"JARVIS1\n{\"probe\":true}") == {"probe": True}
    assert parse_beacon(b"not-json") is None
    assert parse_beacon(encode_beacon({**payload, "server_pin": "short"})) is None


def test_public_beacon_payload_needs_pin_and_endpoint():
    assert public_beacon_payload({"state": "disabled", "endpoints": []}) is None
    snapshot = {
        "server_pin": "b" * 64,
        "endpoints": ["https://10.0.0.5:4781", "https://192.168.1.9:4781"],
    }
    body = public_beacon_payload(snapshot, prefer_host="192.168.1.9")
    assert body["https"] == "https://192.168.1.9:4781"
    assert body["lan_pair"] is True


def test_lan_enroll_is_pending_until_owner_confirms(companion_env):
    key, public = phone_keypair()
    device = identity.enroll_lan(public, "Pixel LAN", client_ip="192.168.1.40")
    assert device["status"] == "pending"
    assert device.get("paired_via") == "lan"
    with pytest.raises(HTTPException) as error:
        identity.exchange(device["id"], _signature(key, device))
    assert error.value.status_code == 403
    with pytest.raises(HTTPException) as confirm_error:
        identity.set_status(device["id"], "active", "0" * 64)
    assert confirm_error.value.status_code == 409
    identity.set_status(device["id"], "active", device["fingerprint"])
    assert identity.exchange(device["id"], _signature(key, device))["access_token"]


def test_lan_enroll_rejects_public_internet_clients(companion_env):
    _, public = phone_keypair()
    with pytest.raises(HTTPException) as error:
        identity.enroll_lan(public, "Remote", client_ip="8.8.8.8")
    assert error.value.status_code == 403


def test_lan_enroll_is_idempotent_for_same_phone(companion_env):
    _, public = phone_keypair()
    first = identity.enroll_lan(public, "One", client_ip="10.0.0.8")
    second = identity.enroll_lan(public, "One again", client_ip="10.0.0.8")
    assert first["id"] == second["id"]


def test_lan_beacon_and_enroll_http(companion_env, monkeypatch):
    from app.mobile import connectivity

    monkeypatch.setattr(
        connectivity.CONNECTIVITY,
        "snapshot",
        lambda: {
            "state": "ready",
            "endpoints": ["https://192.168.1.12:4781"],
            "server_pin": "c" * 64,
        },
    )
    client: TestClient = companion_env["client"]
    beacon = client.get("/api/companion/lan-beacon")
    assert beacon.status_code == 200
    assert beacon.json()["server_pin"] == "c" * 64
    _, public = phone_keypair()
    enrolled = client.post("/api/companion/lan-enroll", json={"public_key": public, "name": "HTTP LAN"})
    assert enrolled.status_code == 200
    assert enrolled.json()["status"] == "pending"
    owner = owner_headers(companion_env["owner_key"])
    devices = client.get("/api/mobile/manage/devices", headers=owner).json()
    pending = [item for item in devices if item["status"] == "pending"]
    assert pending


@pytest.mark.asyncio
async def test_gateway_allows_lan_pair_routes():
    import httpx
    from app.mobile.gateway import gateway_app

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=gateway_app()), base_url="https://jarvis") as client:
        assert (await client.get("/api/companion/lan-beacon")).status_code != 404
        assert (await client.post("/api/auth/generate-key")).status_code == 404
