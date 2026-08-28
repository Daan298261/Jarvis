from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..config import data_dir
from .schema import (
    ActionStatus,
    AdGroupRecord,
    CampaignRecord,
    KeywordRecord,
    MarketingActionAudit,
    MarketingRecommendation,
    PerformanceSnapshot,
    PlacementRecord,
    SearchTermRecord,
)

_lock = threading.RLock()
AMAZON_ADS_ENV = "amazon-ads"


def marketing_root() -> Path:
    path = data_dir() / "marketing"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _campaigns_path(profile_id: str) -> Path:
    return marketing_root() / "campaigns" / f"{profile_id}.json"


def _recommendations_path() -> Path:
    return marketing_root() / "recommendations.json"


def _audit_path() -> Path:
    return marketing_root() / "audit.jsonl"


def _policy_path() -> Path:
    return marketing_root() / "policy.json"


def _connections_path() -> Path:
    return marketing_root() / "connections.json"


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default


def _save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _snapshot_from_dict(raw: dict[str, Any]) -> PerformanceSnapshot:
    return PerformanceSnapshot(
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


def store_campaigns(
    profile_id: str,
    campaigns: list[CampaignRecord],
    ad_groups: list[AdGroupRecord],
    keywords: list[KeywordRecord],
    placements: list[PlacementRecord],
    search_terms: list[SearchTermRecord],
) -> dict[str, Any]:
    payload = {
        "profile_id": profile_id,
        "updated_at": _utcnow(),
        "campaigns": [c.as_dict() for c in campaigns],
        "ad_groups": [a.as_dict() for a in ad_groups],
        "keywords": [k.as_dict() for k in keywords],
        "placements": [p.as_dict() for p in placements],
        "search_terms": [s.as_dict() for s in search_terms],
    }
    with _lock:
        _save_json(_campaigns_path(profile_id), payload)
    return payload


def load_campaign_data(profile_id: str) -> dict[str, Any]:
    with _lock:
        return _load_json(_campaigns_path(profile_id), {})


def list_profile_ids() -> list[str]:
    root = marketing_root() / "campaigns"
    if not root.exists():
        return []
    return sorted(p.stem for p in root.glob("*.json"))


def save_recommendation(rec: MarketingRecommendation) -> MarketingRecommendation:
    with _lock:
        rows = _load_json(_recommendations_path(), [])
        if not isinstance(rows, list):
            rows = []
        rows.append(rec.as_dict())
        _save_json(_recommendations_path(), rows)
    return rec


def list_recommendations(
    *,
    profile_id: str | None = None,
    status: ActionStatus | None = None,
) -> list[MarketingRecommendation]:
    from .schema import EntityType, RecommendationAction

    with _lock:
        rows = _load_json(_recommendations_path(), [])
    out: list[MarketingRecommendation] = []
    for raw in rows:
        if not isinstance(raw, dict):
            continue
        if profile_id and raw.get("profile_id") != profile_id:
            continue
        if status and raw.get("status") != status.value:
            continue
        out.append(
            MarketingRecommendation(
                id=str(raw.get("id") or ""),
                provider=str(raw.get("provider") or ""),
                profile_id=str(raw.get("profile_id") or ""),
                entity_type=EntityType(str(raw.get("entity_type") or "keyword")),
                entity_id=str(raw.get("entity_id") or ""),
                campaign_id=str(raw.get("campaign_id") or ""),
                evidence_window_days=int(raw.get("evidence_window_days") or 0),
                metrics=dict(raw.get("metrics") or {}),
                rationale=str(raw.get("rationale") or ""),
                proposed_action=RecommendationAction(str(raw.get("proposed_action") or "pause")),
                proposed_change=dict(raw.get("proposed_change") or {}),
                estimated_impact=str(raw.get("estimated_impact") or ""),
                confidence=float(raw.get("confidence") or 0),
                originating_agent=str(raw.get("originating_agent") or ""),
                status=ActionStatus(str(raw.get("status") or "suggested")),
                created_at=str(raw.get("created_at") or ""),
            )
        )
    return out


def update_recommendation_status(rec_id: str, status: ActionStatus) -> MarketingRecommendation | None:
    with _lock:
        rows = _load_json(_recommendations_path(), [])
        found: dict[str, Any] | None = None
        for raw in rows:
            if isinstance(raw, dict) and raw.get("id") == rec_id:
                raw["status"] = status.value
                found = raw
                break
        if found is None:
            return None
        _save_json(_recommendations_path(), rows)
    from .schema import EntityType, RecommendationAction

    return MarketingRecommendation(
        id=str(found.get("id") or ""),
        provider=str(found.get("provider") or ""),
        profile_id=str(found.get("profile_id") or ""),
        entity_type=EntityType(str(found.get("entity_type") or "keyword")),
        entity_id=str(found.get("entity_id") or ""),
        campaign_id=str(found.get("campaign_id") or ""),
        evidence_window_days=int(found.get("evidence_window_days") or 0),
        metrics=dict(found.get("metrics") or {}),
        rationale=str(found.get("rationale") or ""),
        proposed_action=RecommendationAction(str(found.get("proposed_action") or "pause")),
        proposed_change=dict(found.get("proposed_change") or {}),
        estimated_impact=str(found.get("estimated_impact") or ""),
        confidence=float(found.get("confidence") or 0),
        originating_agent=str(found.get("originating_agent") or ""),
        status=status,
        created_at=str(found.get("created_at") or ""),
    )


def append_audit(entry: MarketingActionAudit) -> MarketingActionAudit:
    with _lock:
        path = _audit_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry.as_dict()) + "\n")
    return entry


def list_audit_entries(*, recommendation_id: str | None = None) -> list[dict[str, Any]]:
    with _lock:
        path = _audit_path()
        if not path.exists():
            return []
        out: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(raw, dict):
                continue
            if recommendation_id and raw.get("recommendation_id") != recommendation_id:
                continue
            out.append(raw)
        return out


def save_connection(connection: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        rows = _load_json(_connections_path(), [])
        if not isinstance(rows, list):
            rows = []
        conn_id = str(connection.get("id") or uuid.uuid4())
        connection["id"] = conn_id
        connection["updated_at"] = _utcnow()
        replaced = False
        for idx, row in enumerate(rows):
            if isinstance(row, dict) and row.get("id") == conn_id:
                rows[idx] = connection
                replaced = True
                break
        if not replaced:
            connection.setdefault("created_at", _utcnow())
            rows.append(connection)
        _save_json(_connections_path(), rows)
    return connection


def list_connections(*, include_revoked: bool = False) -> list[dict[str, Any]]:
    with _lock:
        rows = _load_json(_connections_path(), [])
    out: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if row.get("revoked_at") and not include_revoked:
            continue
        safe = {k: v for k, v in row.items() if k not in {"access_token", "refresh_token"}}
        out.append(safe)
    return out


def get_connection(connection_id: str) -> dict[str, Any] | None:
    with _lock:
        rows = _load_json(_connections_path(), [])
    for row in rows:
        if isinstance(row, dict) and row.get("id") == connection_id and not row.get("revoked_at"):
            return row
    return None


def revoke_connection(connection_id: str) -> dict[str, Any] | None:
    with _lock:
        rows = _load_json(_connections_path(), [])
        found: dict[str, Any] | None = None
        for row in rows:
            if isinstance(row, dict) and row.get("id") == connection_id:
                row["revoked_at"] = _utcnow()
                row.pop("access_token", None)
                row.pop("refresh_token", None)
                found = row
                break
        if found is None:
            return None
        _save_json(_connections_path(), rows)
    safe = {k: v for k, v in found.items() if k not in {"access_token", "refresh_token"}}
    return safe


def load_policy() -> dict[str, Any]:
    with _lock:
        return _load_json(
            _policy_path(),
            {
                "write_authority": "SUGGEST_ONLY",
                "max_bid_change_pct": 20.0,
                "max_budget_change_pct": 15.0,
                "absolute_daily_spend_ceiling": 500.0,
                "protected_entities": [],
                "min_evidence_days": 7,
                "break_even": {"royalty_rate": 0.35, "margin_rate": 0.0, "other_costs_pct": 0.05},
                "acos_threshold": 0.5,
                "roas_threshold": 2.0,
                "high_spend_no_sale_threshold": 25.0,
                "low_conversion_click_threshold": 50,
                "cpc_change_threshold_pct": 0.25,
            },
        )


def save_policy(policy: dict[str, Any]) -> dict[str, Any]:
    with _lock:
        current = load_policy()
        current.update(policy)
        _save_json(_policy_path(), current)
    return current


def reset_marketing_store() -> None:
    with _lock:
        root = marketing_root()
        if root.exists():
            for path in root.rglob("*"):
                if path.is_file():
                    path.unlink()
            for path in sorted(root.rglob("*"), reverse=True):
                if path.is_dir():
                    path.rmdir()
            if root.exists():
                try:
                    root.rmdir()
                except OSError:
                    pass
