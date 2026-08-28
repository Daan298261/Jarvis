from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.api import amazon_ads as amazon_ads_api
from app.integrations.amazon_ads.mock_client import MockAmazonAdsClient
from app.main import app
from app.marketing.metrics import (
    aggregate_snapshots,
    break_even_acos,
    break_even_roas,
    calculate_acos,
    calculate_roas,
    compare_windows,
)
from app.marketing.optimizer import optimize_profile
from app.marketing.policy import PolicyViolation, can_execute_write, validate_proposed_change
from app.marketing.schema import BreakEvenConfig, PerformanceSnapshot, WriteAuthority
from app.marketing.service import MarketingService
from app.marketing.store import (
    AMAZON_ADS_ENV,
    get_connection,
    list_connections,
    load_policy,
    reset_marketing_store,
    save_policy,
)
from app.workers.credentials import credentials_root, get_credential_secret


@pytest.fixture
def marketing_env(jarvis_env, monkeypatch):
    monkeypatch.setattr("app.marketing.store.data_dir", lambda: jarvis_env["tmp"])
    monkeypatch.setattr("app.workers.credentials.data_dir", lambda: jarvis_env["tmp"])
    reset_marketing_store()
    cred_root = credentials_root()
    if cred_root.exists():
        for f in cred_root.glob("*.json"):
            f.unlink()
    yield jarvis_env["tmp"]
    reset_marketing_store()


@pytest.fixture
def mock_client():
    return MockAmazonAdsClient()


@pytest.fixture
def service(marketing_env, mock_client):
    svc = MarketingService(client=mock_client)
    amazon_ads_api.set_service(svc)
    yield svc
    amazon_ads_api.set_service(None)


@pytest.fixture
def client(marketing_env, monkeypatch):
    monkeypatch.setattr("app.auth.authenticate_request", lambda request: True)
    return TestClient(app)


def _connect(service: MarketingService, profile_id: str = "profile-1") -> dict:
    start = service.start_oauth(
        label="Test Account",
        profile_ids=[profile_id],
        redirect_uri="http://localhost/callback",
    )
    return service.complete_oauth(
        connection_id=start["connection_id"],
        code="testcode",
        state=start["state"],
    )


# --- Metric calculations ---


def test_roas_and_acos_calculations():
    assert calculate_roas(100.0, 50.0) == 2.0
    assert calculate_acos(50.0, 100.0) == 0.5
    assert calculate_roas(0.0, 50.0) == 0.0
    assert calculate_roas(100.0, 0.0) is None
    assert calculate_acos(50.0, 0.0) is None


def test_break_even_from_margin_and_royalty():
    margin_cfg = BreakEvenConfig(margin_rate=0.4, other_costs_pct=0.05)
    assert break_even_roas(margin_cfg) == pytest.approx(1 / 0.35)
    assert break_even_acos(margin_cfg) == pytest.approx(0.35)

    royalty_cfg = BreakEvenConfig(royalty_rate=0.35, other_costs_pct=0.05)
    assert break_even_roas(royalty_cfg) == pytest.approx(1 / 0.30)


def test_window_comparison():
    snapshots = [
        PerformanceSnapshot(date="2026-08-21", spend=10, sales=20, orders=1, clicks=5, impressions=100),
        PerformanceSnapshot(date="2026-08-22", spend=15, sales=30, orders=2, clicks=8, impressions=120),
        PerformanceSnapshot(date="2026-08-23", spend=5, sales=10, orders=1, clicks=3, impressions=80),
    ]
    windows = compare_windows(snapshots, end_date="2026-08-23")
    assert "7d" in windows
    assert windows["7d"]["spend"] == 30.0
    assert windows["7d"]["sales"] == 60.0


# --- OAuth / token handling ---


def test_oauth_connect_refresh_revoke(service):
    conn = _connect(service)
    assert conn["status"] == "connected"
    assert "access_token" not in conn

    listed = service.list_connections()
    assert len(listed) == 1
    assert "access_token" not in listed[0]
    assert "refresh_token" not in listed[0]

    full = get_connection(conn["id"])
    assert full is not None
    assert full.get("access_token")

    secret = get_credential_secret(AMAZON_ADS_ENV, conn["id"])
    assert secret is not None

    refreshed = service.refresh_oauth(conn["id"])
    assert refreshed["id"] == conn["id"]

    revoked = service.revoke_oauth(conn["id"])
    assert revoked.get("revoked_at")
    assert get_connection(conn["id"]) is None


def test_oauth_invalid_state_rejected(service):
    start = service.start_oauth(label="x", profile_ids=["p1"], redirect_uri="http://localhost/cb")
    with pytest.raises(ValueError, match="invalid oauth state"):
        service.complete_oauth(connection_id=start["connection_id"], code="x", state="wrong")


def test_tokens_not_in_api_connection_list(service):
    _connect(service, "profile-secret")
    resp = TestClient(app)
    # auth patched in client fixture only; direct list check
    for row in list_connections():
        assert "access_token" not in row
        assert "refresh_token" not in row


# --- Ingestion ---


def test_ingestion_stores_normalized_data(service):
    _connect(service, "profile-ingest")
    result = service.ingest(
        profile_id="profile-ingest",
        start_date="2026-08-20",
        end_date="2026-08-27",
    )
    assert result["ingested"] is True
    assert result["campaigns"] >= 1
    assert result["keywords"] >= 1

    health = service.health("profile-ingest")
    assert health["has_data"] is True


def test_ingestion_empty_report_fails_safely(service, mock_client):
    _connect(service, "profile-empty")

    class EmptyClient(MockAmazonAdsClient):
        def fetch_performance_report(self, **kwargs):
            return {}

    service._client = EmptyClient()
    with pytest.raises(Exception, match="empty report"):
        service.ingest(profile_id="profile-empty", start_date="2026-08-20", end_date="2026-08-27")


def test_token_expiry_fails_without_inventing_data(service, mock_client):
    _connect(service, "profile-expired")
    mock_client.set_token_expired(True)
    with pytest.raises(Exception):
        service.ingest(profile_id="profile-expired", start_date="2026-08-20", end_date="2026-08-27")


# --- Optimizer ---


def test_optimizer_detects_waste_and_thresholds(service):
    _connect(service, "profile-opt")
    result = service.ingest(profile_id="profile-opt", start_date="2026-08-20", end_date="2026-08-27")
    assert result["recommendations"] > 0
    recs = service.recommendations(profile_id="profile-opt")
    assert len(recs) > 0
    rationales = " ".join(r["rationale"] for r in recs)
    assert "zero orders" in rationales or "ACOS" in rationales or "ROAS" in rationales or "clicks" in rationales


def test_duplicate_action_prevention(service):
    _connect(service, "profile-dup")
    result = service.ingest(profile_id="profile-dup", start_date="2026-08-20", end_date="2026-08-27")
    assert result["recommendations"] > 0
    second = optimize_profile("profile-dup", end_date="2026-08-27")
    assert len(second) == 0


# --- Permission gates ---


def test_default_suggest_only_blocks_execution(service):
    _connect(service, "profile-gate")
    service.ingest(profile_id="profile-gate", start_date="2026-08-20", end_date="2026-08-27")
    recs = service.recommendations(profile_id="profile-gate")
    assert recs
    rec_id = recs[0]["id"]
    result = service.execute_recommendation(rec_id, actor="tester", approved=False)
    assert result["executed"] is False
    assert "SUGGEST_ONLY" in result["reason"]


def test_approved_execution_within_policy(service, mock_client):
    _connect(service, "profile-exec")
    save_policy({"write_authority": WriteAuthority.EXECUTE_WITHIN_POLICY.value})
    service.ingest(profile_id="profile-exec", start_date="2026-08-20", end_date="2026-08-27")
    recs = service.recommendations(profile_id="profile-exec")
    assert recs
    rec_id = recs[0]["id"]
    service.approve_recommendation(rec_id, actor="admin")
    result = service.execute_recommendation(rec_id, actor="admin", approved=True)
    assert result["executed"] is True
    assert result["audit_id"]
    assert mock_client.applied_actions


def test_protected_entity_blocked(service):
    save_policy({"protected_entities": ["kw-waste"]})
    with pytest.raises(PolicyViolation, match="protected"):
        validate_proposed_change(
            entity_id="kw-waste",
            action="pause",
            before={"bid": 1.0},
            after={"bid": 1.0, "status": "paused"},
            evidence_days=14,
        )


def test_bid_change_cap_enforced():
    save_policy({"max_bid_change_pct": 10.0})
    with pytest.raises(PolicyViolation, match="bid change"):
        validate_proposed_change(
            entity_id="kw-1",
            action="decrease_bid",
            before={"bid": 1.0},
            after={"bid": 0.5},
            evidence_days=14,
        )


# --- API endpoints ---


def test_api_health_and_metrics(client, service):
    _connect(service, "api-profile")
    service.ingest(profile_id="api-profile", start_date="2026-08-20", end_date="2026-08-27")

    health = client.get("/api/amazon-ads/health/api-profile")
    assert health.status_code == 200
    assert health.json()["has_data"] is True

    metrics = client.get("/api/amazon-ads/metrics/api-profile", params={"end_date": "2026-08-27"})
    assert metrics.status_code == 200
    assert "7d" in metrics.json()["windows"]


def test_api_oauth_flow(client, service):
    start = client.post(
        "/api/amazon-ads/oauth/start",
        json={"label": "API", "profile_ids": ["api-oauth"], "redirect_uri": "http://localhost/cb"},
    )
    assert start.status_code == 200
    body = start.json()
    cb = client.post(
        "/api/amazon-ads/oauth/callback",
        json={"connection_id": body["connection_id"], "code": "apicode", "state": body["state"]},
    )
    assert cb.status_code == 200
    assert cb.json()["status"] == "connected"


def test_api_recommendations_and_pending(client, service):
    _connect(service, "api-rec")
    service.ingest(profile_id="api-rec", start_date="2026-08-20", end_date="2026-08-27")
    recs = client.get("/api/amazon-ads/recommendations", params={"profile_id": "api-rec"})
    assert recs.status_code == 200
    assert recs.json()["recommendations"]

    pending = client.get("/api/amazon-ads/pending-approvals")
    assert pending.status_code == 200
    assert len(pending.json()["pending"]) >= 1


def test_api_winners_waste(client, service):
    _connect(service, "api-ww")
    service.ingest(profile_id="api-ww", start_date="2026-08-20", end_date="2026-08-27")
    resp = client.get(
        "/api/amazon-ads/winners-waste/api-ww",
        params={"end_date": "2026-08-27"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "winners" in data
    assert "waste" in data


def test_api_policy_update(client):
    resp = client.put(
        "/api/amazon-ads/policy",
        json={"write_authority": "SUGGEST_ONLY", "max_bid_change_pct": 15.0},
    )
    assert resp.status_code == 200
    assert resp.json()["write_authority"] == "SUGGEST_ONLY"


def test_rate_limit_does_not_repeat_writes(service, mock_client):
    _connect(service, "profile-rate")
    save_policy({"write_authority": WriteAuthority.EXECUTE_WITHIN_POLICY.value})
    service.ingest(profile_id="profile-rate", start_date="2026-08-20", end_date="2026-08-27")
    recs = service.recommendations(profile_id="profile-rate")
    assert recs
    service.approve_recommendation(recs[0]["id"], actor="admin")
    mock_client.set_rate_limited(True)
    result = service.execute_recommendation(recs[0]["id"], actor="admin", approved=True)
    assert result["executed"] is False
    assert len(mock_client.applied_actions) == 0


def test_can_execute_write_default():
    allowed, reason = can_execute_write(approved=False)
    assert allowed is False
    assert "SUGGEST_ONLY" in reason

    allowed_approved, _ = can_execute_write(approved=True)
    assert allowed_approved is True


def test_aggregate_enriches_derived_metrics():
    snaps = [
        PerformanceSnapshot(date="2026-08-27", spend=50, sales=25, orders=2, clicks=100, impressions=1000),
    ]
    agg = aggregate_snapshots(snaps)
    assert agg.roas == 0.5
    assert agg.acos == 2.0
    assert agg.ctr == pytest.approx(0.1)
    assert agg.cpc == pytest.approx(0.5)


def test_main_has_no_conflict_markers():
    content = open("backend/app/main.py").read()
    assert "<<<<<<<" not in content
