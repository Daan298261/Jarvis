from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import AppSettings
from app.licensing.cluster import ensure_cluster_identity, get_cluster_id
from app.licensing.entitlements import evaluate_cluster_entitlements, has_feature, has_pack_entitlement
from app.licensing.inference import (
    delete_inference_credential,
    list_inference_credentials,
    upsert_inference_credential,
)
from app.licensing.lease import (
    LeasePayload,
    TEST_SIGNING_PRIVATE_KEY,
    sign_lease,
    verify_lease_signature,
)
from app.licensing.service import LicenseError, refresh_lease, validate_offline
from app.licensing.store import load_inference_credentials, load_state, reset_licensing_store
from app.main import app


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _make_lease(
    cluster_id: str,
    *,
    issued_at: datetime,
    expires_at: datetime,
    grace_seconds: int = 3600,
    tier: str = "pro",
    features: list[str] | None = None,
    pack_entitlements: list[str] | None = None,
    lease_id: str = "lease-001",
):
    payload = LeasePayload(
        lease_id=lease_id,
        cluster_id=cluster_id,
        tier=tier,
        features=features or ["swarm", "packs"],
        pack_entitlements=pack_entitlements or ["specialist.security", "domain.finance"],
        issued_at=_iso(issued_at),
        expires_at=_iso(expires_at),
        grace_seconds=grace_seconds,
    )
    return sign_lease(payload, TEST_SIGNING_PRIVATE_KEY)


@pytest.fixture
def license_store(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.config.data_dir", lambda: jarvis_env["tmp"])
    reset_licensing_store()
    cluster_id = ensure_cluster_identity()
    return {"tmp": jarvis_env["tmp"], "cluster_id": cluster_id}


def test_cluster_identity_is_stable(license_store):
    first = get_cluster_id()
    second = ensure_cluster_identity()
    assert first == second
    assert first.startswith("jarvis-cluster-")


def test_valid_lease_passes_offline_validation(license_store):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    lease = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
    )
    refresh_lease(lease, now=now)
    result = validate_offline(now=now)
    assert result["valid"] is True
    assert result["status"] == "active"
    assert verify_lease_signature(lease)


def test_expired_lease_fails_after_grace(license_store):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    lease = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(days=40),
        expires_at=now - timedelta(days=10),
        grace_seconds=3600,
    )
    refresh_lease(lease, now=now)
    result = validate_offline(now=now)
    assert result["valid"] is False
    assert result["status"] == "expired"


def test_grace_period_allows_offline_validation(license_store):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    lease = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(days=40),
        expires_at=now - timedelta(minutes=30),
        grace_seconds=7200,
    )
    refresh_lease(lease, now=now)
    result = validate_offline(now=now)
    assert result["valid"] is True
    assert result["status"] == "grace"
    assert result["in_grace"] is True


def test_tampered_signature_fails(license_store):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    lease = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
    )
    refresh_lease(lease, now=now)
    state = load_state()
    state["lease"]["signature"] = "invalid"
    from app.licensing.store import save_state

    save_state(state)
    result = validate_offline(now=now)
    assert result["valid"] is False
    assert result["status"] == "invalid_signature"


def test_cluster_mismatch_fails(license_store):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    lease = _make_lease(
        "jarvis-cluster-other",
        issued_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
    )
    with pytest.raises(LicenseError, match="cluster identity"):
        refresh_lease(lease, now=now)


def test_clock_tamper_detection(license_store):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    lease = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
    )
    refresh_lease(lease, now=now)
    validate_offline(now=now)

    earlier = now - timedelta(days=2)
    result = validate_offline(now=earlier)
    assert result["valid"] is False
    assert result["status"] == "tamper_detected"


def test_refresh_reconnect_updates_lease(license_store):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    old = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(days=30),
        expires_at=now - timedelta(days=1),
        lease_id="old-lease",
    )
    refresh_lease(old, now=now - timedelta(days=2))
    assert validate_offline(now=now)["status"] == "expired"

    renewed = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(hours=1),
        expires_at=now + timedelta(days=30),
        lease_id="new-lease",
    )
    refreshed = refresh_lease(renewed, now=now)
    assert refreshed["valid"] is True
    assert refreshed["lease_id"] == "new-lease"


def test_entitlement_failure_does_not_delete_customer_data(license_store):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    lease = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(days=40),
        expires_at=now - timedelta(days=10),
        grace_seconds=0,
    )
    refresh_lease(lease, now=now)
    upsert_inference_credential(
        provider="openai",
        label="BYO key",
        secret="sk-test-secret",
        endpoint="https://api.example.com/v1",
    )
    marker = license_store["tmp"] / "customer-model.txt"
    marker.write_text("keep-me", encoding="utf-8")

    result = validate_offline(now=now)
    assert result["valid"] is False

    creds = load_inference_credentials()
    assert len(creds["credentials"]) == 1
    assert marker.read_text(encoding="utf-8") == "keep-me"
    assert load_state().get("lease") is not None


def test_pack_entitlements_evaluated_cluster_wide(license_store):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    lease = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
        pack_entitlements=["specialist.security", "domain.legal"],
    )
    refresh_lease(lease, now=now)
    stored = validate_offline(now=now)
    assert stored["valid"] is True

    entitlements = evaluate_cluster_entitlements(lease)
    assert entitlements["cluster_wide"] is True
    assert has_pack_entitlement(lease, "specialist.security") is True
    assert has_pack_entitlement(lease, "missing.pack") is False
    assert has_feature(lease, "swarm") is True


def test_inference_credentials_are_separate_from_entitlement(license_store):
    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    assert validate_offline(now=now)["status"] == "unlicensed"

    record = upsert_inference_credential(
        provider="ollama",
        label="Local Ollama",
        secret="not-a-license",
        endpoint="http://127.0.0.1:11434",
    )
    assert record["provider"] == "ollama"
    assert record["secret"] != "not-a-license"
    assert "…" in record["secret"]

    listed = list_inference_credentials()
    assert len(listed) == 1
    assert listed[0]["secret"] != "not-a-license"

    deleted = delete_inference_credential(record["id"])
    assert deleted is True
    assert list_inference_credentials() == []


def test_license_api_endpoints(jarvis_env, license_store, monkeypatch):
    test_key = "jarvis_pk_license_test_key"
    settings = AppSettings(
        allowed_directories=[str(jarvis_env["tmp"])],
        auth_required=True,
        auth_token=test_key,
    )
    monkeypatch.setattr("app.main.load_settings", lambda: settings)
    monkeypatch.setattr("app.auth.load_settings", lambda: settings)

    client = TestClient(app)
    headers = {"X-Jarvis-Key": test_key}

    cluster = client.get("/api/license/cluster", headers=headers)
    assert cluster.status_code == 200
    assert cluster.json()["cluster_id"] == license_store["cluster_id"]

    status = client.get("/api/license/status", headers=headers)
    assert status.status_code == 200
    assert status.json()["validation"]["status"] == "unlicensed"

    now = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)
    lease = _make_lease(
        license_store["cluster_id"],
        issued_at=now - timedelta(days=1),
        expires_at=now + timedelta(days=30),
    )
    refreshed = client.post(
        "/api/license/refresh",
        headers=headers,
        json={"lease": lease.model_dump(mode="json")},
    )
    assert refreshed.status_code == 200
    assert refreshed.json()["valid"] is True

    entitlements = client.get("/api/license/entitlements", headers=headers)
    assert entitlements.status_code == 200
    assert "specialist.security" in entitlements.json()["entitlements"]["pack_entitlements"]

    cred = client.post(
        "/api/license/inference-credentials",
        headers=headers,
        json={
            "provider": "openai",
            "label": "Cloud fallback",
            "secret": "sk-cloud",
            "endpoint": "https://api.openai.com/v1",
        },
    )
    assert cred.status_code == 200
    credential_id = cred.json()["credential"]["id"]

    listed = client.get("/api/license/inference-credentials", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()["credentials"]) == 1

    deleted = client.delete(f"/api/license/inference-credentials/{credential_id}", headers=headers)
    assert deleted.status_code == 200
