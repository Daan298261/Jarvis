from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class EntityType(str, Enum):
    CAMPAIGN = "campaign"
    AD_GROUP = "ad_group"
    KEYWORD = "keyword"
    TARGET = "target"
    PLACEMENT = "placement"
    SEARCH_TERM = "search_term"


class WriteAuthority(str, Enum):
    SUGGEST_ONLY = "SUGGEST_ONLY"
    EXECUTE_WITHIN_POLICY = "EXECUTE_WITHIN_POLICY"


class RecommendationAction(str, Enum):
    PAUSE = "pause"
    UNPAUSE = "unpause"
    DECREASE_BID = "decrease_bid"
    INCREASE_BID = "increase_bid"
    DECREASE_BUDGET = "decrease_budget"
    INCREASE_BUDGET = "increase_budget"
    ADD_NEGATIVE = "add_negative"


class ActionStatus(str, Enum):
    SUGGESTED = "suggested"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    EXECUTED = "executed"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class PerformanceSnapshot:
    date: str
    spend: float = 0.0
    sales: float = 0.0
    orders: int = 0
    clicks: int = 0
    impressions: int = 0
    ctr: float | None = None
    cpc: float | None = None
    conversion_rate: float | None = None
    acos: float | None = None
    roas: float | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CampaignRecord:
    id: str
    provider: str
    profile_id: str
    name: str
    status: str = "enabled"
    budget: float = 0.0
    metrics: list[PerformanceSnapshot] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metrics"] = [m.as_dict() if isinstance(m, PerformanceSnapshot) else m for m in self.metrics]
        return payload


@dataclass
class AdGroupRecord:
    id: str
    campaign_id: str
    name: str
    status: str = "enabled"
    metrics: list[PerformanceSnapshot] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metrics"] = [m.as_dict() if isinstance(m, PerformanceSnapshot) else m for m in self.metrics]
        return payload


@dataclass
class KeywordRecord:
    id: str
    ad_group_id: str
    campaign_id: str
    text: str
    match_type: str = "broad"
    bid: float = 0.0
    status: str = "enabled"
    metrics: list[PerformanceSnapshot] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metrics"] = [m.as_dict() if isinstance(m, PerformanceSnapshot) else m for m in self.metrics]
        return payload


@dataclass
class PlacementRecord:
    id: str
    campaign_id: str
    placement: str
    metrics: list[PerformanceSnapshot] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metrics"] = [m.as_dict() if isinstance(m, PerformanceSnapshot) else m for m in self.metrics]
        return payload


@dataclass
class SearchTermRecord:
    id: str
    campaign_id: str
    ad_group_id: str
    search_term: str
    metrics: list[PerformanceSnapshot] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["metrics"] = [m.as_dict() if isinstance(m, PerformanceSnapshot) else m for m in self.metrics]
        return payload


@dataclass
class MarketingRecommendation:
    id: str
    provider: str
    profile_id: str
    entity_type: EntityType
    entity_id: str
    campaign_id: str
    evidence_window_days: int
    metrics: dict[str, Any]
    rationale: str
    proposed_action: RecommendationAction
    proposed_change: dict[str, Any]
    estimated_impact: str
    confidence: float
    originating_agent: str
    status: ActionStatus = ActionStatus.SUGGESTED
    created_at: str = ""

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entity_type"] = self.entity_type.value
        payload["proposed_action"] = self.proposed_action.value
        payload["status"] = self.status.value
        return payload


@dataclass
class MarketingActionAudit:
    id: str
    recommendation_id: str
    entity_type: EntityType
    entity_id: str
    action: RecommendationAction
    before: dict[str, Any]
    after: dict[str, Any]
    actor: str
    approval_source: str
    timestamp: str
    api_result: dict[str, Any]
    rollback_metadata: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["entity_type"] = self.entity_type.value
        payload["action"] = self.action.value
        return payload


@dataclass
class BreakEvenConfig:
    royalty_rate: float = 0.0
    margin_rate: float = 0.0
    other_costs_pct: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)
