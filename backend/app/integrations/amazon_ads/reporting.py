from __future__ import annotations

from typing import Any

from ...marketing.metrics import enrich_snapshot
from ...marketing.schema import (
    AdGroupRecord,
    CampaignRecord,
    KeywordRecord,
    PerformanceSnapshot,
    PlacementRecord,
    SearchTermRecord,
)


def normalize_report(raw: dict[str, Any], *, profile_id: str) -> dict[str, Any]:
    """Convert Amazon Ads API report payload into provider-independent records."""
    campaigns: list[CampaignRecord] = []
    for row in raw.get("campaigns") or []:
        if not isinstance(row, dict):
            continue
        metrics = [_metric_from_dict(m) for m in row.get("metrics") or [] if isinstance(m, dict)]
        campaigns.append(
            CampaignRecord(
                id=str(row.get("id") or ""),
                provider="amazon_ads",
                profile_id=profile_id,
                name=str(row.get("name") or ""),
                status=str(row.get("status") or "enabled"),
                budget=float(row.get("budget") or 0),
                metrics=metrics,
            )
        )

    ad_groups: list[AdGroupRecord] = []
    for row in raw.get("ad_groups") or []:
        if not isinstance(row, dict):
            continue
        metrics = [_metric_from_dict(m) for m in row.get("metrics") or [] if isinstance(m, dict)]
        ad_groups.append(
            AdGroupRecord(
                id=str(row.get("id") or ""),
                campaign_id=str(row.get("campaign_id") or ""),
                name=str(row.get("name") or ""),
                status=str(row.get("status") or "enabled"),
                metrics=metrics,
            )
        )

    keywords: list[KeywordRecord] = []
    for row in raw.get("keywords") or []:
        if not isinstance(row, dict):
            continue
        metrics = [_metric_from_dict(m) for m in row.get("metrics") or [] if isinstance(m, dict)]
        keywords.append(
            KeywordRecord(
                id=str(row.get("id") or ""),
                ad_group_id=str(row.get("ad_group_id") or ""),
                campaign_id=str(row.get("campaign_id") or ""),
                text=str(row.get("text") or ""),
                match_type=str(row.get("match_type") or "broad"),
                bid=float(row.get("bid") or 0),
                status=str(row.get("status") or "enabled"),
                metrics=metrics,
            )
        )

    placements: list[PlacementRecord] = []
    for row in raw.get("placements") or []:
        if not isinstance(row, dict):
            continue
        metrics = [_metric_from_dict(m) for m in row.get("metrics") or [] if isinstance(m, dict)]
        placements.append(
            PlacementRecord(
                id=str(row.get("id") or ""),
                campaign_id=str(row.get("campaign_id") or ""),
                placement=str(row.get("placement") or ""),
                metrics=metrics,
            )
        )

    search_terms: list[SearchTermRecord] = []
    for row in raw.get("search_terms") or []:
        if not isinstance(row, dict):
            continue
        metrics = [_metric_from_dict(m) for m in row.get("metrics") or [] if isinstance(m, dict)]
        search_terms.append(
            SearchTermRecord(
                id=str(row.get("id") or ""),
                campaign_id=str(row.get("campaign_id") or ""),
                ad_group_id=str(row.get("ad_group_id") or ""),
                search_term=str(row.get("search_term") or ""),
                metrics=metrics,
            )
        )

    return {
        "campaigns": campaigns,
        "ad_groups": ad_groups,
        "keywords": keywords,
        "placements": placements,
        "search_terms": search_terms,
    }


def _metric_from_dict(raw: dict[str, Any]) -> PerformanceSnapshot:
    snap = PerformanceSnapshot(
        date=str(raw.get("date") or ""),
        spend=float(raw.get("spend") or 0),
        sales=float(raw.get("sales") or 0),
        orders=int(raw.get("orders") or 0),
        clicks=int(raw.get("clicks") or 0),
        impressions=int(raw.get("impressions") or 0),
        ctr=raw.get("ctr"),
        cpc=raw.get("cpc"),
        conversion_rate=raw.get("conversion_rate"),
        acos=raw.get("acos"),
        roas=raw.get("roas"),
    )
    return enrich_snapshot(snap)
