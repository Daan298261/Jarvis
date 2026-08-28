from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .metrics import (
    aggregate_snapshots,
    break_even_acos,
    break_even_roas,
    cpc_change_pct,
    window_snapshots,
)
from .policy import get_break_even_config
from .schema import (
    ActionStatus,
    EntityType,
    MarketingRecommendation,
    PerformanceSnapshot,
    RecommendationAction,
)
from .store import list_recommendations, load_campaign_data, load_policy, save_recommendation


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshots(raw_metrics: list[dict[str, Any]]) -> list[PerformanceSnapshot]:
    out: list[PerformanceSnapshot] = []
    for raw in raw_metrics:
        if not isinstance(raw, dict):
            continue
        out.append(
            PerformanceSnapshot(
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
        )
    return out


def _duplicate_exists(
    *,
    profile_id: str,
    entity_id: str,
    proposed_action: RecommendationAction,
) -> bool:
    for rec in list_recommendations(profile_id=profile_id):
        if rec.entity_id != entity_id:
            continue
        if rec.proposed_action != proposed_action:
            continue
        if rec.status in {ActionStatus.SUGGESTED, ActionStatus.PENDING_APPROVAL, ActionStatus.APPROVED}:
            return True
    return False


def _make_recommendation(
    *,
    profile_id: str,
    entity_type: EntityType,
    entity_id: str,
    campaign_id: str,
    window_days: int,
    metrics: dict[str, Any],
    rationale: str,
    action: RecommendationAction,
    proposed_change: dict[str, Any],
    impact: str,
    confidence: float,
    agent: str = "amazon-ads-optimizer",
) -> MarketingRecommendation | None:
    if _duplicate_exists(profile_id=profile_id, entity_id=entity_id, proposed_action=action):
        return None
    rec = MarketingRecommendation(
        id=str(uuid.uuid4()),
        provider="amazon_ads",
        profile_id=profile_id,
        entity_type=entity_type,
        entity_id=entity_id,
        campaign_id=campaign_id,
        evidence_window_days=window_days,
        metrics=metrics,
        rationale=rationale,
        proposed_action=action,
        proposed_change=proposed_change,
        estimated_impact=impact,
        confidence=confidence,
        originating_agent=agent,
        status=ActionStatus.SUGGESTED,
        created_at=_utcnow(),
    )
    save_recommendation(rec)
    return rec


def optimize_profile(profile_id: str, *, end_date: str | None = None) -> list[MarketingRecommendation]:
    policy = load_policy()
    data = load_campaign_data(profile_id)
    if not data:
        return []

    window_days = int(policy.get("min_evidence_days") or 7)
    high_spend_threshold = float(policy.get("high_spend_no_sale_threshold") or 25.0)
    acos_threshold = float(policy.get("acos_threshold") or 0.5)
    roas_threshold = float(policy.get("roas_threshold") or 2.0)
    low_conv_clicks = int(policy.get("low_conversion_click_threshold") or 50)
    cpc_change_threshold = float(policy.get("cpc_change_threshold_pct") or 0.25)

    break_even = get_break_even_config()
    be_roas = break_even_roas(break_even)
    be_acos = break_even_acos(break_even)
    effective_roas_floor = max(roas_threshold, be_roas or 0)
    effective_acos_ceiling = min(acos_threshold, be_acos) if be_acos else acos_threshold

    recommendations: list[MarketingRecommendation] = []

    all_dates: list[str] = []
    for key in ("keywords", "search_terms", "campaigns"):
        for entity in data.get(key) or []:
            for m in entity.get("metrics") or []:
                if isinstance(m, dict) and m.get("date"):
                    all_dates.append(str(m["date"]))
    if not all_dates:
        return []
    end = end_date or max(all_dates)

    def analyze_entity(
        entity: dict[str, Any],
        entity_type: EntityType,
        campaign_id: str,
    ) -> None:
        snapshots = _snapshots(entity.get("metrics") or [])
        if not snapshots:
            return
        current_window = window_snapshots(snapshots, end_date=end, days=window_days)
        prior_window = window_snapshots(snapshots, end_date=end, days=window_days * 2)
        prior_only = [s for s in prior_window if s not in current_window]
        current = aggregate_snapshots(current_window)
        prior = aggregate_snapshots(prior_only)
        entity_id = str(entity.get("id") or "")
        metrics = current.as_dict()

        # High spend, no sales
        if current.spend >= high_spend_threshold and current.orders == 0:
            rec = _make_recommendation(
                profile_id=profile_id,
                entity_type=entity_type,
                entity_id=entity_id,
                campaign_id=campaign_id,
                window_days=window_days,
                metrics=metrics,
                rationale=(
                    f"Spent ${current.spend:.2f} with zero orders in {window_days}d window"
                ),
                action=RecommendationAction.PAUSE,
                proposed_change={"status": "paused"},
                impact=f"Stop ~${current.spend:.2f} waste over {window_days}d",
                confidence=0.85,
            )
            if rec:
                recommendations.append(rec)
            if entity_type == EntityType.SEARCH_TERM:
                neg = _make_recommendation(
                    profile_id=profile_id,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    campaign_id=campaign_id,
                    window_days=window_days,
                    metrics=metrics,
                    rationale=f"High-spend search term with no sales: {entity.get('search_term', '')}",
                    action=RecommendationAction.ADD_NEGATIVE,
                    proposed_change={"negative": entity.get("search_term", "")},
                    impact="Reduce wasted spend on non-converting query",
                    confidence=0.8,
                )
                if neg:
                    recommendations.append(neg)

        # ACOS / ROAS threshold breach
        if current.acos is not None and current.acos > effective_acos_ceiling and current.spend > 0:
            rec = _make_recommendation(
                profile_id=profile_id,
                entity_type=entity_type,
                entity_id=entity_id,
                campaign_id=campaign_id,
                window_days=window_days,
                metrics=metrics,
                rationale=(
                    f"ACOS {current.acos:.2f} exceeds ceiling {effective_acos_ceiling:.2f} "
                    f"(margin-aware break-even considered)"
                ),
                action=RecommendationAction.DECREASE_BID,
                proposed_change={"bid_change_pct": -10},
                impact="Lower CPC to improve ACOS toward break-even",
                confidence=0.75,
            )
            if rec:
                recommendations.append(rec)

        if current.roas is not None and current.roas < effective_roas_floor and current.spend > 0:
            rec = _make_recommendation(
                profile_id=profile_id,
                entity_type=entity_type,
                entity_id=entity_id,
                campaign_id=campaign_id,
                window_days=window_days,
                metrics=metrics,
                rationale=(
                    f"ROAS {current.roas:.2f} below floor {effective_roas_floor:.2f} "
                    f"(not treated as profit without margin context)"
                ),
                action=RecommendationAction.DECREASE_BID,
                proposed_change={"bid_change_pct": -15},
                impact="Reduce spend on underperforming entity",
                confidence=0.78,
            )
            if rec:
                recommendations.append(rec)

        # Low converting, high clicks
        if current.clicks >= low_conv_clicks and (current.conversion_rate or 0) < 0.02:
            rec = _make_recommendation(
                profile_id=profile_id,
                entity_type=entity_type,
                entity_id=entity_id,
                campaign_id=campaign_id,
                window_days=window_days,
                metrics=metrics,
                rationale=(
                    f"{current.clicks} clicks with conversion rate "
                    f"{(current.conversion_rate or 0):.2%} in {window_days}d"
                ),
                action=RecommendationAction.DECREASE_BID,
                proposed_change={"bid_change_pct": -10},
                impact="Reduce bids on low-converting traffic",
                confidence=0.7,
            )
            if rec:
                recommendations.append(rec)

        # Material CPC change
        change = cpc_change_pct(current, prior)
        if change is not None and abs(change) >= cpc_change_threshold and prior.clicks > 10:
            direction = RecommendationAction.INCREASE_BID if change < 0 else RecommendationAction.DECREASE_BID
            pct = min(10, abs(change) * 100)
            rec = _make_recommendation(
                profile_id=profile_id,
                entity_type=entity_type,
                entity_id=entity_id,
                campaign_id=campaign_id,
                window_days=window_days,
                metrics={**metrics, "cpc_change_pct": change},
                rationale=f"CPC changed {change:.1%} vs prior {window_days}d window",
                action=direction,
                proposed_change={"bid_change_pct": pct if direction == RecommendationAction.INCREASE_BID else -pct},
                impact="Respond to material CPC movement",
                confidence=0.65,
            )
            if rec:
                recommendations.append(rec)

    for kw in data.get("keywords") or []:
        if isinstance(kw, dict):
            analyze_entity(kw, EntityType.KEYWORD, str(kw.get("campaign_id") or ""))

    for st in data.get("search_terms") or []:
        if isinstance(st, dict):
            analyze_entity(st, EntityType.SEARCH_TERM, str(st.get("campaign_id") or ""))

    for camp in data.get("campaigns") or []:
        if isinstance(camp, dict):
            analyze_entity(camp, EntityType.CAMPAIGN, str(camp.get("id") or ""))

    return recommendations


def rank_winners_and_waste(profile_id: str, *, end_date: str | None = None, days: int = 30) -> dict[str, Any]:
    data = load_campaign_data(profile_id)
    keywords = data.get("keywords") or []
    all_dates: list[str] = []
    for kw in keywords:
        for m in kw.get("metrics") or []:
            if isinstance(m, dict) and m.get("date"):
                all_dates.append(str(m["date"]))
    if not all_dates:
        return {"winners": [], "waste": []}
    end = end_date or max(all_dates)

    ranked: list[dict[str, Any]] = []
    for kw in keywords:
        if not isinstance(kw, dict):
            continue
        snapshots = _snapshots(kw.get("metrics") or [])
        window = window_snapshots(snapshots, end_date=end, days=days)
        agg = aggregate_snapshots(window)
        ranked.append(
            {
                "entity_id": kw.get("id"),
                "text": kw.get("text"),
                "campaign_id": kw.get("campaign_id"),
                **agg.as_dict(),
            }
        )

    winners = sorted(
        [r for r in ranked if (r.get("roas") or 0) > 1 and r.get("orders", 0) > 0],
        key=lambda x: x.get("roas") or 0,
        reverse=True,
    )[:10]
    waste = sorted(
        [r for r in ranked if r.get("spend", 0) > 0 and r.get("orders", 0) == 0],
        key=lambda x: x.get("spend") or 0,
        reverse=True,
    )[:10]
    return {"winners": winners, "waste": waste}
