"""Live Amazon Ads API client — OAuth, profiles, and reporting ingest."""

from __future__ import annotations

import gzip
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode

import httpx

from .client import AmazonAdsClient, AmazonAdsError, RateLimitError, TokenExpiredError

logger = logging.getLogger(__name__)

TOKEN_URL = "https://api.amazon.com/auth/o2/token"
AUTH_URL = "https://www.amazon.com/ap/oa"
REVOKE_URL = "https://api.amazon.com/auth/O2/revoke"
OAUTH_SCOPE = "advertising::campaign_management"

REGION_API_BASE: dict[str, str] = {
    "na": "https://advertising-api.amazon.com",
    "eu": "https://advertising-api-eu.amazon.com",
    "fe": "https://advertising-api-fe.amazon.com",
}

_REPORT_POLL_INTERVAL_S = 2.0
_REPORT_POLL_MAX_ATTEMPTS = 30


class LiveAmazonAdsClient(AmazonAdsClient):
    """Official Amazon Ads API adapter with safe failure modes."""

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        region: str = "na",
        refresh_token: str | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._region = region if region in REGION_API_BASE else "na"
        self._default_refresh_token = refresh_token
        self._http = http_client or httpx.Client(timeout=60.0)
        self._owns_client = http_client is None

    @property
    def api_base(self) -> str:
        return REGION_API_BASE[self._region]

    def close(self) -> None:
        if self._owns_client:
            self._http.close()

    def __enter__(self) -> LiveAmazonAdsClient:
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    # --- OAuth ---

    def build_authorization_url(self, *, state: str, redirect_uri: str) -> str:
        params = {
            "client_id": self._client_id,
            "scope": OAUTH_SCOPE,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
        }
        return f"{AUTH_URL}?{urlencode(params)}"

    def exchange_code(self, *, code: str, redirect_uri: str) -> dict[str, Any]:
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        data = self._token_request(payload)
        return {
            "access_token": data.get("access_token"),
            "refresh_token": data.get("refresh_token"),
            "expires_at": _expires_at(data.get("expires_in")),
        }

    def refresh_token(self, *, refresh_token: str) -> dict[str, Any]:
        token = refresh_token or self._default_refresh_token
        if not token:
            raise TokenExpiredError("no refresh token available")
        payload = {
            "grant_type": "refresh_token",
            "refresh_token": token,
            "client_id": self._client_id,
            "client_secret": self._client_secret,
        }
        data = self._token_request(payload)
        return {
            "access_token": data.get("access_token"),
            "expires_at": _expires_at(data.get("expires_in")),
        }

    def revoke_token(self, *, connection_id: str) -> dict[str, Any]:
        token = self._default_refresh_token
        if token:
            try:
                self._http.post(
                    REVOKE_URL,
                    data={"token": token, "client_id": self._client_id, "client_secret": self._client_secret},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            except httpx.HTTPError as exc:
                logger.warning("Amazon token revoke request failed for %s: %s", connection_id, exc)
        return {"revoked": True, "connection_id": connection_id}

    # --- Profiles ---

    def fetch_profiles(self, *, access_token: str) -> list[dict[str, Any]]:
        """List advertising profiles for the authorized account."""
        response = self._api_request("GET", "/v2/profiles", access_token=access_token)
        if not isinstance(response, list):
            raise AmazonAdsError("unexpected profiles response")
        return [row for row in response if isinstance(row, dict)]

    # --- Reporting ---

    def fetch_performance_report(
        self,
        *,
        profile_id: str,
        start_date: str,
        end_date: str,
        access_token: str,
    ) -> dict[str, Any]:
        if not access_token:
            raise TokenExpiredError("access token required")

        campaign_rows = self._fetch_report_rows(
            profile_id=profile_id,
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            report_type_id="spCampaigns",
            group_by=["campaign"],
            columns=[
                "campaignId",
                "campaignName",
                "campaignStatus",
                "campaignBudgetAmount",
                "impressions",
                "clicks",
                "cost",
                "sales14d",
                "purchases14d",
            ],
        )
        keyword_rows = self._fetch_report_rows(
            profile_id=profile_id,
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            report_type_id="spKeywords",
            group_by=["campaign", "adGroup", "keyword"],
            columns=[
                "campaignId",
                "adGroupId",
                "keywordId",
                "keyword",
                "keywordBid",
                "keywordStatus",
                "impressions",
                "clicks",
                "cost",
                "sales14d",
                "purchases14d",
            ],
        )
        search_term_rows = self._fetch_report_rows(
            profile_id=profile_id,
            access_token=access_token,
            start_date=start_date,
            end_date=end_date,
            report_type_id="spSearchTerm",
            group_by=["campaign", "adGroup", "searchTerm"],
            columns=[
                "campaignId",
                "adGroupId",
                "searchTerm",
                "impressions",
                "clicks",
                "cost",
                "sales14d",
                "purchases14d",
            ],
        )

        if not campaign_rows and not keyword_rows and not search_term_rows:
            raise AmazonAdsError("report unavailable — no rows returned")

        return _assemble_report(
            profile_id=profile_id,
            start_date=start_date,
            end_date=end_date,
            campaign_rows=campaign_rows,
            keyword_rows=keyword_rows,
            search_term_rows=search_term_rows,
        )

    # --- Write actions ---

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
        if not access_token:
            raise TokenExpiredError("access token required")

        if entity_type in {"keyword", "target"} and action in {"pause", "unpause"}:
            state = "PAUSED" if action == "pause" else "ENABLED"
            body = {"keywords": [{"keywordId": entity_id, "state": state}]}
            result = self._api_request(
                "PUT",
                "/sp/keywords",
                access_token=access_token,
                profile_id=profile_id,
                json_body=body,
            )
            return {"ok": True, "profile_id": profile_id, "entity_type": entity_type, "entity_id": entity_id, "action": action, "api_result": result}

        if entity_type in {"keyword", "target"} and action in {"decrease_bid", "increase_bid"}:
            bid = change.get("bid")
            if bid is None:
                raise AmazonAdsError("bid change missing target bid")
            body = {"keywords": [{"keywordId": entity_id, "bid": float(bid)}]}
            result = self._api_request(
                "PUT",
                "/sp/keywords",
                access_token=access_token,
                profile_id=profile_id,
                json_body=body,
            )
            return {"ok": True, "profile_id": profile_id, "entity_type": entity_type, "entity_id": entity_id, "action": action, "api_result": result}

        if entity_type == "campaign" and action in {"pause", "unpause"}:
            state = "PAUSED" if action == "pause" else "ENABLED"
            body = {"campaigns": [{"campaignId": entity_id, "state": state}]}
            result = self._api_request(
                "PUT",
                "/sp/campaigns",
                access_token=access_token,
                profile_id=profile_id,
                json_body=body,
            )
            return {"ok": True, "profile_id": profile_id, "entity_type": entity_type, "entity_id": entity_id, "action": action, "api_result": result}

        raise AmazonAdsError(f"unsupported action {action} for {entity_type}")

    # --- HTTP helpers ---

    def _token_request(self, payload: dict[str, str]) -> dict[str, Any]:
        try:
            response = self._http.post(
                TOKEN_URL,
                data=payload,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except httpx.HTTPError as exc:
            raise AmazonAdsError(f"token request failed: {exc}") from exc
        return _parse_response(response, context="token")

    def _api_request(
        self,
        method: str,
        path: str,
        *,
        access_token: str,
        profile_id: str | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> Any:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Amazon-Advertising-API-ClientId": self._client_id,
            "Content-Type": "application/vnd.createasyncreportrequest.v3+json"
            if path.startswith("/reporting/")
            else "application/json",
        }
        if profile_id:
            headers["Amazon-Advertising-API-Scope"] = profile_id
        url = f"{self.api_base}{path}"
        try:
            response = self._http.request(method, url, headers=headers, json=json_body)
        except httpx.HTTPError as exc:
            raise AmazonAdsError(f"API request failed: {exc}") from exc
        return _parse_response(response, context=path)

    def _fetch_report_rows(
        self,
        *,
        profile_id: str,
        access_token: str,
        start_date: str,
        end_date: str,
        report_type_id: str,
        group_by: list[str],
        columns: list[str],
    ) -> list[dict[str, Any]]:
        create_body = {
            "name": f"jarvis-{report_type_id}-{start_date}-{end_date}",
            "startDate": _amazon_date(start_date),
            "endDate": _amazon_date(end_date),
            "configuration": {
                "adProduct": "SPONSORED_PRODUCTS",
                "groupBy": group_by,
                "columns": columns,
                "reportTypeId": report_type_id,
                "timeUnit": "DAILY",
                "format": "GZIP_JSON",
            },
        }
        created = self._api_request(
            "POST",
            "/reporting/reports",
            access_token=access_token,
            profile_id=profile_id,
            json_body=create_body,
        )
        if not isinstance(created, dict):
            raise AmazonAdsError(f"invalid report create response for {report_type_id}")
        report_id = str(created.get("reportId") or "")
        if not report_id:
            raise AmazonAdsError(f"missing report id for {report_type_id}")

        download_url = self._poll_report(profile_id=profile_id, access_token=access_token, report_id=report_id)
        if not download_url:
            raise AmazonAdsError(f"report {report_id} unavailable")
        return self._download_report_rows(download_url)

    def _poll_report(self, *, profile_id: str, access_token: str, report_id: str) -> str | None:
        for _ in range(_REPORT_POLL_MAX_ATTEMPTS):
            status_payload = self._api_request(
                "GET",
                f"/reporting/reports/{report_id}",
                access_token=access_token,
                profile_id=profile_id,
            )
            if not isinstance(status_payload, dict):
                raise AmazonAdsError("invalid report status response")
            status = str(status_payload.get("status") or "").upper()
            if status == "COMPLETED":
                url = status_payload.get("url")
                return str(url) if url else None
            if status in {"FAILED", "CANCELLED"}:
                raise AmazonAdsError(f"report {report_id} failed with status {status}")
            time.sleep(_REPORT_POLL_INTERVAL_S)
        raise AmazonAdsError(f"report {report_id} timed out")

    def _download_report_rows(self, url: str) -> list[dict[str, Any]]:
        try:
            response = self._http.get(url)
        except httpx.HTTPError as exc:
            raise AmazonAdsError(f"report download failed: {exc}") from exc
        if response.status_code >= 400:
            _raise_for_status(response, context="report-download")
        raw = response.content
        try:
            decoded = gzip.decompress(raw)
        except OSError:
            decoded = raw
        try:
            payload = json.loads(decoded)
        except json.JSONDecodeError as exc:
            raise AmazonAdsError("report download is not valid JSON") from exc
        if isinstance(payload, list):
            return [row for row in payload if isinstance(row, dict)]
        if isinstance(payload, dict):
            rows = payload.get("rows") or payload.get("data") or []
            if isinstance(rows, list):
                return [row for row in rows if isinstance(row, dict)]
        raise AmazonAdsError("unexpected report payload shape")


def _parse_response(response: httpx.Response, *, context: str) -> Any:
    if response.status_code == 401:
        raise TokenExpiredError(f"unauthorized ({context})")
    if response.status_code == 429:
        raise RateLimitError(f"rate limit exceeded ({context})")
    if response.status_code >= 400:
        _raise_for_status(response, context=context)
    if not response.content:
        return {}
    try:
        return response.json()
    except json.JSONDecodeError as exc:
        raise AmazonAdsError(f"invalid JSON response ({context})") from exc


def _raise_for_status(response: httpx.Response, *, context: str) -> None:
    detail = response.text[:200] if response.text else response.status_code
    raise AmazonAdsError(f"{context} failed: {detail}")


def _expires_at(expires_in: Any) -> str | None:
    try:
        seconds = int(expires_in)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(time.time() + seconds, tz=timezone.utc).isoformat()


def _amazon_date(iso_date: str) -> str:
    return iso_date.replace("-", "")


def _iso_date(amazon_date: str) -> str:
    if len(amazon_date) == 8 and amazon_date.isdigit():
        return f"{amazon_date[:4]}-{amazon_date[4:6]}-{amazon_date[6:8]}"
    return amazon_date


def _metric_from_row(row: dict[str, Any]) -> dict[str, Any]:
    spend = float(row.get("cost") or row.get("spend") or 0)
    sales = float(row.get("sales14d") or row.get("sales") or 0)
    orders = int(row.get("purchases14d") or row.get("orders") or 0)
    clicks = int(row.get("clicks") or 0)
    impressions = int(row.get("impressions") or 0)
    date_raw = str(row.get("date") or "")
    return {
        "date": _iso_date(date_raw),
        "spend": spend,
        "sales": sales,
        "orders": orders,
        "clicks": clicks,
        "impressions": impressions,
    }


def _assemble_report(
    *,
    profile_id: str,
    start_date: str,
    end_date: str,
    campaign_rows: list[dict[str, Any]],
    keyword_rows: list[dict[str, Any]],
    search_term_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    campaigns: dict[str, dict[str, Any]] = {}
    ad_groups: dict[str, dict[str, Any]] = {}
    keywords: dict[str, dict[str, Any]] = {}
    search_terms: dict[str, dict[str, Any]] = {}

    for row in campaign_rows:
        cid = str(row.get("campaignId") or row.get("campaign_id") or "")
        if not cid:
            continue
        camp = campaigns.setdefault(
            cid,
            {
                "id": cid,
                "name": str(row.get("campaignName") or row.get("name") or cid),
                "status": _normalize_status(row.get("campaignStatus") or row.get("status")),
                "budget": float(row.get("campaignBudgetAmount") or row.get("budget") or 0),
                "metrics": [],
            },
        )
        camp["metrics"].append(_metric_from_row(row))

    for row in keyword_rows:
        kid = str(row.get("keywordId") or row.get("keyword_id") or "")
        cid = str(row.get("campaignId") or "")
        agid = str(row.get("adGroupId") or "")
        if agid and agid not in ad_groups:
            ad_groups[agid] = {
                "id": agid,
                "campaign_id": cid,
                "name": f"Ad group {agid}",
                "status": "enabled",
                "metrics": [],
            }
        if not kid:
            continue
        kw = keywords.setdefault(
            kid,
            {
                "id": kid,
                "ad_group_id": agid,
                "campaign_id": cid,
                "text": str(row.get("keyword") or row.get("text") or kid),
                "bid": float(row.get("keywordBid") or row.get("bid") or 0),
                "status": _normalize_status(row.get("keywordStatus") or row.get("status")),
                "metrics": [],
            },
        )
        kw["metrics"].append(_metric_from_row(row))

    for row in search_term_rows:
        term = str(row.get("searchTerm") or row.get("search_term") or "")
        cid = str(row.get("campaignId") or "")
        agid = str(row.get("adGroupId") or "")
        sid = f"{cid}:{agid}:{term}" if term else ""
        if not sid:
            continue
        st = search_terms.setdefault(
            sid,
            {
                "id": sid,
                "campaign_id": cid,
                "ad_group_id": agid,
                "search_term": term,
                "metrics": [],
            },
        )
        st["metrics"].append(_metric_from_row(row))

    return {
        "profile_id": profile_id,
        "start_date": start_date,
        "end_date": end_date,
        "campaigns": list(campaigns.values()),
        "ad_groups": list(ad_groups.values()),
        "keywords": list(keywords.values()),
        "placements": [],
        "search_terms": list(search_terms.values()),
    }


def _normalize_status(raw: Any) -> str:
    value = str(raw or "enabled").lower()
    if value in {"enabled", "active"}:
        return "enabled"
    if value in {"paused", "archived"}:
        return "paused"
    return value
