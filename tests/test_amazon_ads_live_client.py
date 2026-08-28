from __future__ import annotations

import gzip
import json
from typing import Any

import httpx
import pytest

from fastapi.testclient import TestClient

from app.api import amazon_ads as amazon_ads_api
from app.integrations.amazon_ads.client import AmazonAdsError, RateLimitError, TokenExpiredError
from app.integrations.amazon_ads.factory import (
    CLIENT_MODE_ENV,
    REQUIRED_ENV_VARS,
    client_mode_info,
    create_amazon_ads_client,
    resolve_client_credentials,
)
from app.integrations.amazon_ads.live_client import LiveAmazonAdsClient
from app.integrations.amazon_ads.mock_client import MockAmazonAdsClient
from app.main import app
from app.marketing.service import MarketingService
from app.marketing.store import AMAZON_ADS_ENV, reset_marketing_store
from app.workers.credentials import credentials_root, store_credential


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


@pytest.fixture(autouse=True)
def clear_amazon_env(monkeypatch):
    for name in (*REQUIRED_ENV_VARS, CLIENT_MODE_ENV):
        monkeypatch.delenv(name, raising=False)


# --- Factory ---


def test_factory_defaults_to_mock_without_env():
    client = create_amazon_ads_client()
    assert isinstance(client, MockAmazonAdsClient)


def test_factory_respects_mock_mode_env(monkeypatch):
    monkeypatch.setenv(CLIENT_MODE_ENV, "mock")
    monkeypatch.setenv("AMAZON_ADS_CLIENT_ID", "cid")
    monkeypatch.setenv("AMAZON_ADS_CLIENT_SECRET", "csecret")
    client = create_amazon_ads_client()
    assert isinstance(client, MockAmazonAdsClient)


def test_factory_falls_back_to_mock_when_live_credentials_missing(monkeypatch):
    monkeypatch.setenv(CLIENT_MODE_ENV, "live")
    client = create_amazon_ads_client()
    assert isinstance(client, MockAmazonAdsClient)


def test_factory_uses_live_when_configured(monkeypatch):
    monkeypatch.setenv(CLIENT_MODE_ENV, "live")
    monkeypatch.setenv("AMAZON_ADS_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("AMAZON_ADS_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("AMAZON_ADS_REGION", "na")
    client = create_amazon_ads_client()
    assert isinstance(client, LiveAmazonAdsClient)


def test_factory_reads_vault_credentials(marketing_env, monkeypatch):
    store_credential(
        AMAZON_ADS_ENV,
        capability="amazon_ads.client_id",
        label="app-client-id",
        secret="vault-client-id",
    )
    store_credential(
        AMAZON_ADS_ENV,
        capability="amazon_ads.client_secret",
        label="app-client-secret",
        secret="vault-client-secret",
    )
    monkeypatch.setenv(CLIENT_MODE_ENV, "live")
    creds = resolve_client_credentials()
    assert creds["client_id"] == "vault-client-id"
    assert creds["client_secret"] == "vault-client-secret"
    client = create_amazon_ads_client()
    assert isinstance(client, LiveAmazonAdsClient)


def test_client_mode_info_documents_env_names(monkeypatch):
    info = client_mode_info()
    assert info["effective_mode"] == "mock"
    assert info["requested_mode"] == "mock"
    assert "AMAZON_ADS_CLIENT_ID" in info["required_env_vars"]
    assert "client_secret" not in str(info)


# --- Live client HTTP mocks ---


def _gzip_json(payload: Any) -> bytes:
    return gzip.compress(json.dumps(payload).encode("utf-8"))


def _make_transport(handlers: dict[tuple[str, str], Any]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        key = (request.method.upper(), request.url.path)
        for (method, path), fn in handlers.items():
            if method == request.method.upper() and request.url.path.startswith(path):
                return fn(request)
        if key in handlers:
            fn = handlers[key]
            return fn(request) if callable(fn) else fn
        return httpx.Response(404, text=f"unhandled {request.method} {request.url}")

    return httpx.MockTransport(handler)


def _token_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json={"access_token": "live-access", "refresh_token": "live-refresh", "expires_in": 3600})


def _profiles_response(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=[{"profileId": 12345, "countryCode": "US", "accountInfo": {"name": "Test"}}])


def _report_flow(rows: list[dict[str, Any]]):
    state = {"polls": 0}

    def create(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"reportId": "rpt-1", "status": "PENDING"})

    def status(_request: httpx.Request) -> httpx.Response:
        state["polls"] += 1
        return httpx.Response(200, json={"reportId": "rpt-1", "status": "COMPLETED", "url": "https://reports.example/data.gz"})

    def download(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_gzip_json(rows))

    return create, status, download


@pytest.fixture
def live_client(monkeypatch):
    monkeypatch.setattr("app.integrations.amazon_ads.live_client._REPORT_POLL_INTERVAL_S", 0)
    campaign_rows = [
        {
            "date": "20260827",
            "campaignId": "camp-live",
            "campaignName": "Live Campaign",
            "campaignStatus": "ENABLED",
            "campaignBudgetAmount": 150.0,
            "impressions": 1000,
            "clicks": 50,
            "cost": 40.0,
            "sales14d": 20.0,
            "purchases14d": 1,
        }
    ]
    keyword_rows = [
        {
            "date": "20260827",
            "campaignId": "camp-live",
            "adGroupId": "ag-live",
            "keywordId": "kw-live",
            "keyword": "live keyword",
            "keywordBid": 1.1,
            "keywordStatus": "ENABLED",
            "impressions": 200,
            "clicks": 10,
            "cost": 8.0,
            "sales14d": 0.0,
            "purchases14d": 0,
        }
    ]
    search_rows = [
        {
            "date": "20260827",
            "campaignId": "camp-live",
            "adGroupId": "ag-live",
            "searchTerm": "live search",
            "impressions": 100,
            "clicks": 5,
            "cost": 3.0,
            "sales14d": 0.0,
            "purchases14d": 0,
        }
    ]
    create_c, status_c, download_c = _report_flow(campaign_rows)
    create_k, status_k, download_k = _report_flow(keyword_rows)
    create_s, status_s, download_s = _report_flow(search_rows)
    report_calls = {"create": 0}

    def reporting_create(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        report_type = body["configuration"]["reportTypeId"]
        report_calls["create"] += 1
        if report_type == "spCampaigns":
            return create_c(request)
        if report_type == "spKeywords":
            return create_k(request)
        if report_type == "spSearchTerm":
            return create_s(request)
        return httpx.Response(400, json={"message": "unknown report"})

    transport = _make_transport(
        {
            ("POST", "/auth/o2/token"): _token_response,
            ("GET", "/v2/profiles"): _profiles_response,
            ("POST", "/reporting/reports"): reporting_create,
            ("GET", "/reporting/reports/rpt-1"): status_c,
            ("GET", "https://reports.example/data.gz"): download_c,
        }
    )

    def download_router(request: httpx.Request) -> httpx.Response:
        if "reports.example" in str(request.url):
            # Return based on how many report creates happened
            if report_calls["create"] <= 1:
                return download_c(request)
            if report_calls["create"] == 2:
                return download_k(request)
            return download_s(request)
        if request.url.path.endswith("/reporting/reports/rpt-1"):
            return status_c(request)
        return httpx.Response(404)

    transport = httpx.MockTransport(
        lambda request: (
            _token_response(request)
            if request.url.path == "/auth/o2/token"
            else _profiles_response(request)
            if request.url.path == "/v2/profiles"
            else reporting_create(request)
            if request.method == "POST" and request.url.path == "/reporting/reports"
            else status_c(request)
            if request.method == "GET" and request.url.path.endswith("/reporting/reports/rpt-1")
            else download_router(request)
            if "reports.example" in str(request.url)
            else httpx.Response(404, text=f"unhandled {request.method} {request.url}")
        )
    )
    http = httpx.Client(transport=transport)
    client = LiveAmazonAdsClient(
        client_id="test-client-id",
        client_secret="test-client-secret",
        region="na",
        http_client=http,
    )
    yield client
    client.close()


def test_live_oauth_exchange_and_refresh(live_client):
    tokens = live_client.exchange_code(code="abc", redirect_uri="http://localhost/cb")
    assert tokens["access_token"] == "live-access"
    assert tokens["refresh_token"] == "live-refresh"
    refreshed = live_client.refresh_token(refresh_token="live-refresh")
    assert refreshed["access_token"] == "live-access"


def test_live_fetch_profiles(live_client):
    profiles = live_client.fetch_profiles(access_token="live-access")
    assert len(profiles) == 1
    assert profiles[0]["profileId"] == 12345


def test_live_fetch_performance_report(live_client):
    report = live_client.fetch_performance_report(
        profile_id="12345",
        start_date="2026-08-27",
        end_date="2026-08-27",
        access_token="live-access",
    )
    assert report["profile_id"] == "12345"
    assert len(report["campaigns"]) == 1
    assert report["campaigns"][0]["id"] == "camp-live"
    assert report["campaigns"][0]["metrics"][0]["spend"] == 40.0
    assert len(report["keywords"]) == 1
    assert report["keywords"][0]["text"] == "live keyword"
    assert len(report["search_terms"]) == 1


def test_live_report_401_raises_token_expired(monkeypatch):
    monkeypatch.setattr("app.integrations.amazon_ads.live_client._REPORT_POLL_INTERVAL_S", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/reporting/reports":
            return httpx.Response(401, json={"message": "unauthorized"})
        return httpx.Response(404)

    client = LiveAmazonAdsClient(
        client_id="id",
        client_secret="secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(TokenExpiredError):
        client.fetch_performance_report(
            profile_id="1",
            start_date="2026-08-27",
            end_date="2026-08-27",
            access_token="bad",
        )
    client.close()


def test_live_report_429_raises_rate_limit(monkeypatch):
    monkeypatch.setattr("app.integrations.amazon_ads.live_client._REPORT_POLL_INTERVAL_S", 0)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/reporting/reports":
            return httpx.Response(429, json={"message": "too many requests"})
        return httpx.Response(404)

    client = LiveAmazonAdsClient(
        client_id="id",
        client_secret="secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(RateLimitError):
        client.fetch_performance_report(
            profile_id="1",
            start_date="2026-08-27",
            end_date="2026-08-27",
            access_token="token",
        )
    client.close()


def test_live_empty_report_raises_without_inventing_data(monkeypatch):
    monkeypatch.setattr("app.integrations.amazon_ads.live_client._REPORT_POLL_INTERVAL_S", 0)

    def create(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"reportId": "rpt-empty", "status": "PENDING"})

    def status(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"reportId": "rpt-empty", "status": "COMPLETED", "url": "https://reports.example/empty.gz"},
        )

    def download(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_gzip_json([]))

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/reporting/reports":
            return create(request)
        if request.url.path.endswith("/reporting/reports/rpt-empty"):
            return status(request)
        if "reports.example" in str(request.url):
            return download(request)
        return httpx.Response(404)

    client = LiveAmazonAdsClient(
        client_id="id",
        client_secret="secret",
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(AmazonAdsError, match="no rows returned"):
        client.fetch_performance_report(
            profile_id="1",
            start_date="2026-08-27",
            end_date="2026-08-27",
            access_token="token",
        )
    client.close()


def test_health_includes_client_mode(client, service):
    resp = client.get("/api/amazon-ads/health/test-profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["client"]["effective_mode"] == "mock"
    assert "AMAZON_ADS_CLIENT_ID" in body["client"]["required_env_vars"]
