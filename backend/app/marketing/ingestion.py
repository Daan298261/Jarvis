from __future__ import annotations

import logging
from typing import Any

from ..integrations.amazon_ads.client import AmazonAdsClient, AmazonAdsError
from ..integrations.amazon_ads.reporting import normalize_report
from .optimizer import optimize_profile
from .store import get_connection, list_profile_ids, store_campaigns

logger = logging.getLogger(__name__)


class IngestionError(RuntimeError):
    """Raised when ingestion cannot complete safely."""


def ingest_profile(
    client: AmazonAdsClient,
    *,
    profile_id: str,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    connection = _connection_for_profile(profile_id)
    if connection is None:
        raise IngestionError(f"no active connection for profile {profile_id}")

    try:
        raw = client.fetch_performance_report(
            profile_id=profile_id,
            start_date=start_date,
            end_date=end_date,
            access_token=str(connection.get("access_token") or ""),
        )
    except AmazonAdsError as exc:
        logger.warning("Amazon Ads report fetch failed for %s: %s", profile_id, exc)
        raise IngestionError(str(exc)) from exc

    if not raw:
        raise IngestionError("empty report — refusing to invent data")

    normalized = normalize_report(raw, profile_id=profile_id)
    store_campaigns(
        profile_id,
        normalized["campaigns"],
        normalized["ad_groups"],
        normalized["keywords"],
        normalized["placements"],
        normalized["search_terms"],
    )
    recommendations = optimize_profile(profile_id, end_date=end_date)
    return {
        "profile_id": profile_id,
        "ingested": True,
        "campaigns": len(normalized["campaigns"]),
        "keywords": len(normalized["keywords"]),
        "recommendations": len(recommendations),
        "start_date": start_date,
        "end_date": end_date,
    }


def ingest_all_profiles(
    client: AmazonAdsClient,
    *,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []
    profile_ids = _active_profile_ids()
    for profile_id in profile_ids:
        try:
            results.append(
                ingest_profile(client, profile_id=profile_id, start_date=start_date, end_date=end_date)
            )
        except IngestionError as exc:
            errors.append({"profile_id": profile_id, "error": str(exc)})
            logger.warning("Partial ingestion failure for %s: %s", profile_id, exc)
    return {"results": results, "errors": errors, "partial_failure": bool(errors)}


def _connection_for_profile(profile_id: str) -> dict[str, Any] | None:
    from .store import list_connections

    for conn in list_connections(include_revoked=False):
        profiles = conn.get("profile_ids") or []
        if profile_id in profiles:
            return get_connection(str(conn.get("id") or ""))
    return None


def _active_profile_ids() -> list[str]:
    from .store import list_connections

    ids: list[str] = []
    for conn in list_connections():
        for pid in conn.get("profile_ids") or []:
            if pid not in ids:
                ids.append(str(pid))
    stored = list_profile_ids()
    for pid in stored:
        if pid not in ids:
            ids.append(pid)
    return ids
