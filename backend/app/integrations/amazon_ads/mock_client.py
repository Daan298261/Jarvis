from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .client import AmazonAdsClient, AmazonAdsError, RateLimitError, TokenExpiredError

_FIXTURE_ROOT = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "amazon_ads"


class MockAmazonAdsClient(AmazonAdsClient):
    """Deterministic mock — no live Amazon API calls."""

    def __init__(self, *, fixture_name: str = "sample_report.json") -> None:
        self._fixture_name = fixture_name
        self._revoked: set[str] = set()
        self._applied_actions: list[dict[str, Any]] = []
        self._rate_limited = False
        self._token_expired = False

    def set_rate_limited(self, value: bool) -> None:
        self._rate_limited = value

    def set_token_expired(self, value: bool) -> None:
        self._token_expired = value

    @property
    def applied_actions(self) -> list[dict[str, Any]]:
        return list(self._applied_actions)

    def build_authorization_url(self, *, state: str, redirect_uri: str) -> str:
        return f"https://mock.amazon.com/ap/oa?state={state}&redirect_uri={redirect_uri}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> dict[str, Any]:
        if code == "invalid":
            raise AmazonAdsError("invalid authorization code")
        return {
            "access_token": f"mock_access_{code}",
            "refresh_token": f"mock_refresh_{code}",
            "expires_at": _utcnow(),
        }

    def refresh_token(self, *, refresh_token: str) -> dict[str, Any]:
        if self._token_expired or refresh_token.endswith("_expired"):
            raise TokenExpiredError("refresh token expired")
        return {
            "access_token": f"mock_access_refreshed_{refresh_token[-8:]}",
            "expires_at": _utcnow(),
        }

    def revoke_token(self, *, connection_id: str) -> dict[str, Any]:
        self._revoked.add(connection_id)
        return {"revoked": True, "connection_id": connection_id}

    def fetch_performance_report(
        self,
        *,
        profile_id: str,
        start_date: str,
        end_date: str,
        access_token: str,
    ) -> dict[str, Any]:
        if self._rate_limited:
            raise RateLimitError("rate limit exceeded")
        if self._token_expired or not access_token:
            raise TokenExpiredError("access token expired")
        if access_token in self._revoked:
            raise TokenExpiredError("token revoked")

        fixture = _FIXTURE_ROOT / self._fixture_name
        if fixture.exists():
            payload = json.loads(fixture.read_text(encoding="utf-8"))
            payload["profile_id"] = profile_id
            payload["start_date"] = start_date
            payload["end_date"] = end_date
            return payload

        return _default_fixture(profile_id, start_date, end_date)

    def apply_action(
        self,
        *,
        profile_id: str,
        entity_type: str,
        entity_id: str,
        action: str,
        change: dict[str, Any],
        access_token: str,
    ) -> dict[str, Any]:
        if self._rate_limited:
            raise RateLimitError("rate limit exceeded")
        if self._token_expired or not access_token:
            raise TokenExpiredError("access token expired")

        result = {
            "ok": True,
            "profile_id": profile_id,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "change": change,
            "mock": True,
        }
        self._applied_actions.append(result)
        return result


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _default_fixture(profile_id: str, start_date: str, end_date: str) -> dict[str, Any]:
    return {
        "profile_id": profile_id,
        "start_date": start_date,
        "end_date": end_date,
        "campaigns": [
            {
                "id": "camp-1",
                "name": "Brand Campaign",
                "status": "enabled",
                "budget": 100.0,
                "metrics": [
                    {"date": "2026-08-20", "spend": 45.0, "sales": 20.0, "orders": 1, "clicks": 80, "impressions": 2000},
                    {"date": "2026-08-21", "spend": 50.0, "sales": 0.0, "orders": 0, "clicks": 90, "impressions": 2100},
                    {"date": "2026-08-22", "spend": 55.0, "sales": 15.0, "orders": 1, "clicks": 95, "impressions": 2200},
                    {"date": "2026-08-23", "spend": 60.0, "sales": 10.0, "orders": 0, "clicks": 100, "impressions": 2300},
                    {"date": "2026-08-24", "spend": 30.0, "sales": 5.0, "orders": 0, "clicks": 55, "impressions": 1500},
                    {"date": "2026-08-25", "spend": 35.0, "sales": 8.0, "orders": 1, "clicks": 60, "impressions": 1600},
                    {"date": "2026-08-26", "spend": 40.0, "sales": 12.0, "orders": 1, "clicks": 65, "impressions": 1700},
                    {"date": "2026-08-27", "spend": 42.0, "sales": 18.0, "orders": 2, "clicks": 70, "impressions": 1800},
                ],
            }
        ],
        "ad_groups": [
            {"id": "ag-1", "campaign_id": "camp-1", "name": "Core", "status": "enabled", "metrics": []},
        ],
        "keywords": [
            {
                "id": "kw-waste",
                "ad_group_id": "ag-1",
                "campaign_id": "camp-1",
                "text": "expensive term",
                "bid": 1.5,
                "status": "enabled",
                "metrics": [
                    {"date": f"2026-08-{d:02d}", "spend": 8.0, "sales": 0.0, "orders": 0, "clicks": 12, "impressions": 300}
                    for d in range(20, 28)
                ],
            },
            {
                "id": "kw-winner",
                "ad_group_id": "ag-1",
                "campaign_id": "camp-1",
                "text": "profitable term",
                "bid": 0.8,
                "status": "enabled",
                "metrics": [
                    {"date": f"2026-08-{d:02d}", "spend": 5.0, "sales": 25.0, "orders": 2, "clicks": 10, "impressions": 200}
                    for d in range(20, 28)
                ],
            },
            {
                "id": "kw-lowconv",
                "ad_group_id": "ag-1",
                "campaign_id": "camp-1",
                "text": "high clicks low conv",
                "bid": 1.2,
                "status": "enabled",
                "metrics": [
                    {"date": f"2026-08-{d:02d}", "spend": 15.0, "sales": 5.0, "orders": 0, "clicks": 55, "impressions": 800}
                    for d in range(20, 28)
                ],
            },
        ],
        "placements": [
            {
                "id": "pl-1",
                "campaign_id": "camp-1",
                "placement": "top_of_search",
                "metrics": [
                    {"date": "2026-08-27", "spend": 20.0, "sales": 30.0, "orders": 2, "clicks": 40, "impressions": 500}
                ],
            }
        ],
        "search_terms": [
            {
                "id": "st-waste",
                "campaign_id": "camp-1",
                "ad_group_id": "ag-1",
                "search_term": "free ebook pdf",
                "metrics": [
                    {"date": f"2026-08-{d:02d}", "spend": 6.0, "sales": 0.0, "orders": 0, "clicks": 8, "impressions": 150}
                    for d in range(20, 28)
                ],
            }
        ],
    }
