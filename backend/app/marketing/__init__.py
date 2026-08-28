"""Provider-independent marketing data model, ingestion, and optimization."""

from .schema import (
    AdGroupRecord,
    CampaignRecord,
    EntityType,
    KeywordRecord,
    MarketingRecommendation,
    PerformanceSnapshot,
    PlacementRecord,
    SearchTermRecord,
    WriteAuthority,
)
from .service import MarketingService

__all__ = [
    "AdGroupRecord",
    "CampaignRecord",
    "EntityType",
    "KeywordRecord",
    "MarketingRecommendation",
    "MarketingService",
    "PerformanceSnapshot",
    "PlacementRecord",
    "SearchTermRecord",
    "WriteAuthority",
]
