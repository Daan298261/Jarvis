from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .metrics import aggregate_snapshots, compare_windows
from .schema import PerformanceSnapshot
from .store import list_audit_entries, load_campaign_data


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshots_from_entity(entity: dict[str, Any]) -> list[PerformanceSnapshot]:
    out: list[PerformanceSnapshot] = []
    for raw in entity.get("metrics") or []:
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


def evaluate_action(
    *,
    profile_id: str,
    recommendation_id: str,
    entity_type: str,
    entity_id: str,
    action_date: str | None = None,
) -> dict[str, Any]:
    """Link post-change performance to the recommendation/action that caused it."""
    audits = list_audit_entries(recommendation_id=recommendation_id)
    if not audits:
        return {
            "recommendation_id": recommendation_id,
            "status": "no_audit",
            "evaluated_at": _utcnow(),
        }

    data = load_campaign_data(profile_id)
    entity_key = {
        "keyword": "keywords",
        "target": "keywords",
        "campaign": "campaigns",
        "ad_group": "ad_groups",
        "search_term": "search_terms",
        "placement": "placements",
    }.get(entity_type, "keywords")

    entity: dict[str, Any] | None = None
    for row in data.get(entity_key) or []:
        if isinstance(row, dict) and row.get("id") == entity_id:
            entity = row
            break

    if entity is None:
        return {
            "recommendation_id": recommendation_id,
            "status": "entity_not_found",
            "evaluated_at": _utcnow(),
        }

    snapshots = _snapshots_from_entity(entity)
    if not snapshots:
        return {
            "recommendation_id": recommendation_id,
            "status": "no_metrics",
            "evaluated_at": _utcnow(),
        }

    dates = sorted(s.date for s in snapshots)
    end_date = action_date or dates[-1]
    pre_action = [s for s in snapshots if s.date < end_date]
    post_action = [s for s in snapshots if s.date >= end_date]

    pre = aggregate_snapshots(pre_action[-14:] if pre_action else [])
    post = aggregate_snapshots(post_action[:14] if post_action else [])

    evaluation_id = str(uuid.uuid4())
    improved = False
    if pre.roas is not None and post.roas is not None:
        improved = post.roas > pre.roas
    elif pre.acos is not None and post.acos is not None:
        improved = post.acos < pre.acos

    return {
        "id": evaluation_id,
        "recommendation_id": recommendation_id,
        "profile_id": profile_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "action_date": end_date,
        "pre_metrics": pre.as_dict(),
        "post_metrics": post.as_dict(),
        "windows": compare_windows(snapshots, end_date=end_date),
        "improved": improved,
        "status": "evaluated",
        "evaluated_at": _utcnow(),
        "audit_count": len(audits),
    }
