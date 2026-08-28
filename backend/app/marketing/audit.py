from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from .schema import EntityType, MarketingActionAudit, RecommendationAction
from .store import append_audit, list_audit_entries


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def record_action_audit(
    *,
    recommendation_id: str,
    entity_type: EntityType,
    entity_id: str,
    action: RecommendationAction,
    before: dict[str, Any],
    after: dict[str, Any],
    actor: str,
    approval_source: str,
    api_result: dict[str, Any],
    rollback_metadata: dict[str, Any] | None = None,
) -> MarketingActionAudit:
    entry = MarketingActionAudit(
        id=str(uuid.uuid4()),
        recommendation_id=recommendation_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        before=dict(before),
        after=dict(after),
        actor=actor,
        approval_source=approval_source,
        timestamp=_utcnow(),
        api_result=dict(api_result),
        rollback_metadata=dict(rollback_metadata or {}),
    )
    return append_audit(entry)


def get_audit_trail(*, recommendation_id: str | None = None) -> list[dict[str, Any]]:
    return list_audit_entries(recommendation_id=recommendation_id)
