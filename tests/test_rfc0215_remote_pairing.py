"""RFC-0215 off-LAN companion pairing (Tailscale only): ordering, gating, lockout, proofs, migration."""
from __future__ import annotations

import asyncio
import base64
import json

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from fastapi import HTTPException

from app.mobile import remote_access as ra


def test_only_tailscale_and_lan_reach_the_qr_tailscale_first():
    entries = ra.ordered_entries(
        [
            "https://abc.trycloudflare.com",
            "https://anzu.example.com",
            "https://203.0.113.9:4781",
            "https://192.168.1.20:4781",
            "https://vrpc.tail1234.ts.net:4781",
            "https://100.101.102.103:4781",
            "https://[fd7a:115c:a1e0::9]:4781",
            "https://192.168.1.20:4781",
            "http://insecure.example.com",
        ]
    )
    assert [e["url"] for e in entries] == [
        "https://vrpc.tail1234.ts.net:4781",
        "https://100.101.102.103:4781",
        "https://[fd7a:115c:a1e0::9]:4781",
        "https://192.168.1.20:4781",
    ]
    assert [e["kind"] for e in entries] == ["tailscale", "tailscale", "tailscale", "lan"]


def test_self_test_reports_each_endpoint():
    async def probe(url):
        if "10.9" in url:
            raise OSError("refused")

    results = asyncio.run(ra.self_test(ra.ordered_entries(["https://100.64.0.9:4781", "https://10.9.0.1:4781"]), probe))
    assert [(r["kind"], r["status"]) for r in results] == [("tailscale", "ok"), ("lan", "failed")]


def test_exposure_summary():
    assert "LAN only" in ra.exposure_summary(False, [])
    text = ra.exposure_summary(True, ra.ordered_entries(["https://100.64.0.9:4781"]))
    assert "tailscale=https://100.64.0.9:4781" in text and "pairing" in text


def test_connectivity_adds_tailscale_only_when_remote_on(monkeypatch):
    from app.mobile import connectivity

    conn = connectivity.Connectivity()
    status = {"running": True, "endpoints": ["https://vrpc.tail1.ts.net:4781", "https://100.90.1.2:4781"], "hint": ""}
    monkeypatch.setattr(ra, "tailscale_status", lambda: status)
    assert asyncio.run(conn._remote_endpoints({"remote": False})) == []
    assert asyncio.run(conn._remote_endpoints({"remote": True})) == status["endpoints"]
    assert asyncio.run(conn._remote_endpoints({"remote": True, "tailscale": False})) == []
    monkeypatch.setattr(ra, "tailscale_status", lambda: {"running": False, "endpoints": [], "hint": "sign in"})
    assert asyncio.run(conn._remote_endpoints({"remote": True})) == []
    assert conn.state["limitation"] == "sign in"


def test_tailscale_status_parsing_and_missing():
    raw = json.dumps({
        "BackendState": "Running",
        "Self": {"DNSName": "vrpc.tail1234.ts.net.", "TailscaleIPs": ["100.90.1.2", "fd7a:115c:a1e0::9"], "Online": True},
        "CurrentTailnet": {"Name": "taco@example.com"},
    })
    status = ra.tailscale_status(runner=lambda args: raw)
    assert status["running"] and status["dns_name"] == "vrpc.tail1234.ts.net"
    assert status["endpoints"][0] == "https://vrpc.tail1234.ts.net:4781"
    assert "https://[fd7a:115c:a1e0::9]:4781" in status["endpoints"]
    stopped = ra.parse_tailscale_status(json.dumps({"BackendState": "NeedsLogin", "Self": {}}))
    assert not stopped["running"] and stopped["endpoints"] == [] and "sign in" in stopped["hint"]


def test_tailscale_not_installed(monkeypatch):
    monkeypatch.setattr(ra, "_tailscale_binary", lambda: "")
    status = ra.tailscale_status()
    assert status["installed"] is False and "tailscale.com/download" in status["hint"]


def test_gateway_gate_lan_tailscale_loopback_public():
    from app.mobile.gateway import SELF_TEST_SECRET, client_allowed

    assert client_allowed("192.168.1.4", False)
    assert not client_allowed("100.64.0.9", False)
    assert client_allowed("100.64.0.9", True)
    assert not client_allowed("203.0.113.4", True)  # public internet is never allowed
    for remote in (False, True):
        assert not client_allowed("127.0.0.1", remote)
        assert not client_allowed("127.0.0.1", remote, "wrong")
        assert client_allowed("127.0.0.1", remote, SELF_TEST_SECRET)


def test_server_proof_verifies_against_pin(tmp_path, monkeypatch):
    from app.mobile import gateway

    monkeypatch.setattr(gateway, "root", lambda: tmp_path)
    identity = gateway.server_identity(["127.0.0.1"])
    proof = gateway.server_proof("nonce123")
    der = base64.b64decode(proof["server_key"])
    import hashlib

    assert hashlib.sha256(der).hexdigest() == identity["server_pin"]
    key = serialization.load_der_public_key(der)
    key.verify(base64.b64decode(proof["server_signature"]), b"anzu-server-v1\nnonce123", ec.ECDSA(hashes.SHA256()))


@pytest.fixture
def mobile_store(tmp_path, monkeypatch):
    from app.config import AppSettings
    from app.mobile import identity, store

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    settings = AppSettings(allowed_directories=[str(tmp_path)], auth_required=True, auth_token="jarvis_pk_rfc0215_owner")
    monkeypatch.setattr("app.mobile.identity.load_settings", lambda: settings)
    monkeypatch.setattr(identity, "_remote_enabled", lambda: False)
    return identity


def _phone_key() -> str:
    key = ec.generate_private_key(ec.SECP256R1())
    return base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    ).decode()


def test_global_lockout_burns_code_across_ips(mobile_store):
    identity = mobile_store
    real = identity.generate_pairing_code(10)["code"]
    wrong = "000001" if real != "000001" else "000002"
    for i in range(identity.GLOBAL_FAILED_CODE_LIMIT):
        with pytest.raises(HTTPException) as exc:
            identity.enroll_pairing_code(wrong, _phone_key(), "x", client_ip=f"203.0.113.{i}")
        assert exc.value.status_code == 401
    assert identity.pairing_lockout_remaining() > 0
    with pytest.raises(HTTPException) as locked:
        identity.enroll_pairing_code(real, _phone_key(), "phone", client_ip="198.51.100.1")
    assert locked.value.status_code == 423
    assert identity.pairing_code_status()["active"] is False
    # Owner explicitly generating a new code clears the lock.
    fresh = identity.generate_pairing_code(10)["code"]
    assert identity.pairing_lockout_remaining() == 0
    assert identity.enroll_pairing_code(fresh, _phone_key(), "phone", client_ip="198.51.100.1")["status"] == "pending"


def test_remote_caps_code_lifetime(mobile_store, monkeypatch):
    identity = mobile_store
    monkeypatch.setattr(identity, "_remote_enabled", lambda: True)
    assert identity.generate_pairing_code(60)["ttl_seconds"] == identity.REMOTE_MAX_PAIRING_TTL_MINUTES * 60
    monkeypatch.setattr(identity, "_remote_enabled", lambda: False)
    assert identity.generate_pairing_code(60)["ttl_seconds"] == 3600


def test_challenge_with_nonce_carries_server_proof(mobile_store, monkeypatch, tmp_path):
    from app.mobile import gateway

    identity = mobile_store
    monkeypatch.setattr(gateway, "root", lambda: tmp_path)
    gateway.server_identity(["127.0.0.1"])
    code = identity.generate_pairing_code(10)["code"]
    device = identity.enroll_pairing_code(code, _phone_key(), "phone", client_ip="192.168.1.5")
    plain = identity.challenge(device["id"])
    assert "server_signature" not in plain
    proved = identity.challenge(device["id"], "abcDEF_123")
    assert proved["challenge"] == plain["challenge"] and proved["server_signature"]


def _gateway_client(monkeypatch, remote: bool):
    from fastapi.testclient import TestClient
    from app.mobile import gateway

    monkeypatch.setattr(gateway, "_remote_enabled", lambda: remote)
    return TestClient(gateway.gateway_app("http://127.0.0.1:9"), client=("127.0.0.1", 5555)), gateway


def test_gateway_returns_403_for_loopback_without_self_test_secret(monkeypatch):
    client, gateway = _gateway_client(monkeypatch, remote=False)
    response = client.get("/api/companion/health")
    assert response.status_code == 403 and "Remote access is off" in response.json()["detail"]
    # Our own probe passes the gate (upstream is down here, so it gets the offline 503, not 403).
    allowed = client.get("/api/companion/health", headers={gateway.SELF_TEST_HEADER: gateway.SELF_TEST_SECRET})
    assert allowed.status_code == 503


def test_remote_setting_read_failure_fails_closed(monkeypatch, caplog):
    from app.mobile import connectivity, gateway, identity

    def boom():
        raise RuntimeError("db locked")

    monkeypatch.setattr(connectivity.CONNECTIVITY, "config", boom)
    gateway._REMOTE_CACHE["at"] = 0.0
    with caplog.at_level("ERROR"):
        assert gateway._remote_enabled() is False
        assert identity._remote_enabled() is True  # -> 10-minute code cap
    assert "treating remote access as off" in caplog.text and "capping pairing codes" in caplog.text
    gateway._REMOTE_CACHE["at"] = 0.0


@pytest.fixture
def network_store(tmp_path, monkeypatch):
    from app.mobile import store

    monkeypatch.setattr(store, "data_dir", lambda: tmp_path)
    return store


def test_migration_turns_implicit_remote_off_once(network_store):
    from app.mobile import connectivity

    with network_store.database() as db:
        network_store.put(db, "network", "config", {"enabled": True, "remote": True, "marker": "Jarvis-x"})
    conn = connectivity.Connectivity()
    first = conn.config()
    assert first["remote"] is False and first["rfc0215_migrated"] is True
    # After migration an explicit owner choice sticks.
    with network_store.database() as db:
        network_store.put(db, "network", "config", {**first, "remote": True, "remote_explicit": True})
    assert conn.config()["remote"] is True


def test_migration_keeps_explicit_remote(network_store):
    from app.mobile import connectivity

    with network_store.database() as db:
        network_store.put(db, "network", "config", {"enabled": True, "remote": True, "remote_explicit": True})
    assert connectivity.Connectivity().config()["remote"] is True


def test_toggling_remote_invalidates_unclaimed_codes(network_store, monkeypatch):
    from app.config import AppSettings
    from app.mobile import connectivity, identity

    settings = AppSettings(auth_required=True, auth_token="jarvis_pk_rfc0215_owner")
    monkeypatch.setattr("app.mobile.identity.load_settings", lambda: settings)
    conn = connectivity.Connectivity()

    async def no_apply(config):
        return None

    monkeypatch.setattr(conn, "apply_remote", no_apply)
    monkeypatch.setattr(identity, "_remote_enabled", lambda: False)
    identity.generate_pairing_code(60)
    assert identity.pairing_code_status()["active"] is True
    asyncio.run(conn.configure(True, None))  # remote unchanged -> code survives
    assert identity.pairing_code_status()["active"] is True
    asyncio.run(conn.configure(True, True))
    assert identity.pairing_code_status()["active"] is False
    assert conn.config()["remote_explicit"] is True
    identity.generate_pairing_code(60)
    asyncio.run(conn.configure(True, False))  # toggling off burns codes too
    assert identity.pairing_code_status()["active"] is False


def test_turning_remote_off_takes_effect_immediately(network_store, monkeypatch):
    """The gateway caches the remote flag for 5 s; configure() must drop that cache."""
    from app.mobile import connectivity, gateway

    conn = connectivity.Connectivity()

    async def no_apply(config):
        return None

    monkeypatch.setattr(conn, "apply_remote", no_apply)
    monkeypatch.setattr(connectivity, "CONNECTIVITY", conn)
    gateway.invalidate_remote_cache()
    asyncio.run(conn.configure(True, True))
    assert gateway._remote_enabled() is True  # now cached as on
    assert gateway.client_allowed("100.101.1.2", gateway._remote_enabled())
    asyncio.run(conn.configure(True, False))
    # Same instant, well inside the 5 s cache window: the Tailscale client is refused.
    assert gateway._remote_enabled() is False
    assert not gateway.client_allowed("100.101.1.2", gateway._remote_enabled())
    gateway.invalidate_remote_cache()


def test_tailscale_status_nonzero_exit_is_an_error_and_logged(monkeypatch, caplog):
    import subprocess as sp

    monkeypatch.setattr(ra, "_tailscale_binary", lambda: "tailscale")
    running_json = json.dumps({"BackendState": "Running", "Self": {"DNSName": "vrpc.tail1.ts.net.", "TailscaleIPs": ["100.101.1.2"]}})
    monkeypatch.setattr(
        ra.subprocess, "run",
        lambda *a, **k: sp.CompletedProcess(a[0], 1, stdout=running_json, stderr="failed to connect to local tailscaled"),
    )
    with caplog.at_level("WARNING"):
        status = ra.tailscale_status()
    # Even with plausible stdout, a failing exit code must not advertise Tailscale endpoints.
    assert status["running"] is False and status["endpoints"] == [] and status["backend_state"] == "error"
    assert "tailscaled" in status["hint"]
    assert "Could not read Tailscale status" in caplog.text
