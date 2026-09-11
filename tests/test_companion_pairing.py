from __future__ import annotations

import base64
import json
import time

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.main import app
from app.mobile import identity, store


@pytest.fixture
def companion_env(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    settings = AppSettings(
        allowed_directories=[str(tmp_path)],
        auth_required=True,
        auth_token="jarvis_pk_companion_pairing_owner",
    )
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)
    monkeypatch.setattr("app.mobile.identity.load_settings", lambda: settings)
    return {
        "tmp": tmp_path,
        "owner_key": settings.auth_token,
        "client": TestClient(app),
    }


def phone_keypair():
    key = ec.generate_private_key(ec.SECP256R1())
    public = base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    ).decode()
    return key, public


def owner_headers(owner_key: str) -> dict[str, str]:
    return {"X-Jarvis-Key": owner_key}


def stored_pairing_payloads(tmp_path) -> list[dict]:
    db_path = tmp_path / "mobile" / "companion.db"
    if not db_path.exists():
        return []
    import sqlite3

    conn = sqlite3.connect(db_path)
    rows = conn.execute("SELECT payload FROM records WHERE kind='pairing_code'").fetchall()
    conn.close()
    return [json.loads(row[0]) for row in rows]


def test_generate_pairing_code_returns_six_digits(companion_env):
    result = identity.generate_pairing_code()
    assert len(result["code"]) == 6
    assert result["code"].isdigit()
    assert result["ttl_seconds"] == identity.DEFAULT_PAIRING_TTL_MINUTES * 60
    assert result["expires_at"] > time.time()


def test_generate_rejects_obvious_codes(companion_env):
    for _ in range(40):
        code = identity.generate_pairing_code()["code"]
        assert code not in identity.OBVIOUS_PAIRING_CODES


def test_pairing_code_hashed_at_rest(companion_env):
    result = identity.generate_pairing_code()
    blob = json.dumps(stored_pairing_payloads(companion_env["tmp"]))
    assert result["code"] not in blob
    assert identity.hash_pairing_code(result["code"]) in blob


def test_regenerate_invalidates_prior_unclaimed_code(companion_env):
    first = identity.generate_pairing_code()
    second = identity.generate_pairing_code()
    assert first["code"] != second["code"]
    _, public = phone_keypair()
    with pytest.raises(HTTPException) as error:
        identity.enroll_pairing_code(first["code"], public, "Old code", client_ip="10.0.0.1")
    assert error.value.status_code == 401
    device = identity.enroll_pairing_code(second["code"], public, "New code", client_ip="10.0.0.1")
    assert device["name"] == "New code"


def test_expired_pairing_code_rejected(companion_env, monkeypatch):
    generated = identity.generate_pairing_code(ttl_minutes=5)
    _, public = phone_keypair()
    monkeypatch.setattr(identity.time, "time", lambda: generated["expires_at"] + 1)
    with pytest.raises(HTTPException) as error:
        identity.enroll_pairing_code(generated["code"], public, "Late", client_ip="10.0.0.2")
    assert error.value.status_code == 401


def test_claim_pairing_code_and_confirm_device(companion_env):
    generated = identity.generate_pairing_code()
    _, public = phone_keypair()
    device = identity.enroll_pairing_code(generated["code"], public, "Pixel", client_ip="10.0.0.3")
    assert device["status"] == "pending"
    status = identity.pairing_code_status()
    assert status["claimed"] is True
    assert status["active"] is False
    with pytest.raises(HTTPException):
        identity.set_status(device["id"], "active", "0" * 64)
    active = identity.set_status(device["id"], "active", device["fingerprint"])
    assert active["status"] == "active"


def test_enroll_rate_limit_per_ip(companion_env):
    _, public = phone_keypair()
    client_ip = "192.168.1.50"
    for _ in range(identity.ENROLL_RATE_LIMIT):
        with pytest.raises(HTTPException):
            identity.enroll_pairing_code("000001", public, "Try", client_ip=client_ip)
    with pytest.raises(HTTPException) as error:
        identity.enroll_pairing_code("000001", public, "Blocked", client_ip=client_ip)
    assert error.value.status_code == 429


def test_legacy_long_invitation_still_works(companion_env):
    _, public = phone_keypair()
    invitation = identity.invite()
    device = identity.enroll(invitation["invitation"], public, "Legacy phone", client_ip="10.0.0.4")
    assert device["status"] == "pending"
    assert len(invitation["invitation"]) >= 20


def test_owner_pairing_api_endpoints(companion_env):
    client = companion_env["client"]
    owner = owner_headers(companion_env["owner_key"])
    create = client.post("/api/mobile/manage/pairing-codes", headers=owner, json={"ttl_minutes": 12})
    assert create.status_code == 200
    body = create.json()
    assert len(body["code"]) == 6
    regen = client.post("/api/mobile/manage/pairing-codes/regenerate", headers=owner, json={"ttl_minutes": 15})
    assert regen.status_code == 200
    assert regen.json()["code"] != body["code"]
    status = client.get("/api/mobile/manage/pairing-codes/status", headers=owner)
    assert status.status_code == 200
    assert status.json()["active"] is True


def test_companion_enroll_accepts_code_without_owner_key(companion_env):
    client = companion_env["client"]
    owner = owner_headers(companion_env["owner_key"])
    generated = client.post("/api/mobile/manage/pairing-codes", headers=owner, json={}).json()
    _, public = phone_keypair()
    response = client.post(
        "/api/companion/enroll",
        json={"code": generated["code"], "public_key": public, "name": "HTTP phone"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"


@pytest.fixture
def companion_env_no_owner_key(tmp_path, monkeypatch):
    monkeypatch.setattr("app.config.data_dir", lambda: tmp_path)
    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    settings = AppSettings(
        allowed_directories=[str(tmp_path)],
        auth_required=True,
        auth_token="",
    )
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)
    monkeypatch.setattr("app.mobile.identity.load_settings", lambda: settings)
    return {
        "tmp": tmp_path,
        "client": TestClient(app, client=("127.0.0.1", 47880)),
    }


def test_pairing_codes_auto_mint_owner_key_without_prior_key(companion_env_no_owner_key, caplog):
    client = companion_env_no_owner_key["client"]
    with caplog.at_level("INFO"):
        create = client.post("/api/mobile/manage/pairing-codes", json={"ttl_minutes": 10})
    assert create.status_code == 200
    body = create.json()
    assert len(body["code"]) == 6
    from app.auth import get_effective_private_key, private_key_file_path

    assert get_effective_private_key()
    assert private_key_file_path().exists()
    assert not any("jarvis_pk_" in record.message for record in caplog.records)
    status = client.get("/api/mobile/manage/pairing-codes/status")
    assert status.status_code == 200
    assert status.json()["active"] is True
    assert status.json()["code"] == body["code"]


def test_pairing_status_includes_qr_fields_when_connection_ready(companion_env, monkeypatch):
    from app.mobile import connectivity

    monkeypatch.setattr(
        connectivity.CONNECTIVITY,
        "snapshot",
        lambda: {
            "state": "ready",
            "endpoints": ["https://192.168.1.5:4781"],
            "server_pin": "a" * 64,
        },
    )
    client = companion_env["client"]
    owner = owner_headers(companion_env["owner_key"])
    created = client.post("/api/mobile/manage/pairing-codes", headers=owner, json={}).json()
    assert created["endpoint"] == "https://192.168.1.5:4781"
    assert created["qr"]["code"] == created["code"]
    assert created["qr"]["server_pin"] == "a" * 64


def test_companion_onboarding_snapshot_offers_pair_and_explore(companion_env):
    client = companion_env["client"]
    response = client.get("/api/mobile/onboarding/companion")
    assert response.status_code == 200
    body = response.json()
    assert body["version"] == 1
    offer_ids = {item["id"] for item in body["offers"]}
    assert offer_ids == {"pair_phone", "explore_features"}
    assert all("spoken_prompt" in item for item in body["offers"])


def test_companion_enroll_legacy_invitation_without_owner_key(companion_env):
    client = companion_env["client"]
    owner = owner_headers(companion_env["owner_key"])
    invitation = client.post("/api/mobile/manage/invitations", headers=owner).json()
    _, public = phone_keypair()
    response = client.post(
        "/api/companion/enroll",
        json={"invitation": invitation["invitation"], "public_key": public, "name": "Legacy HTTP"},
    )
    assert response.status_code == 200
    assert response.json()["status"] == "pending"
