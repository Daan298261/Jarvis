from __future__ import annotations

from typing import Any

from ..agent.proactivity import (
    PROACTIVITY_EXECUTE_WITHIN_POLICY,
    PROACTIVITY_SUGGEST_ONLY,
    can_enqueue_executable_work,
)
from .schema import BreakEvenConfig, WriteAuthority
from .store import load_policy


class PolicyViolation(ValueError):
    """Raised when a proposed write violates marketing policy."""


def get_write_authority() -> WriteAuthority:
    policy = load_policy()
    raw = str(policy.get("write_authority") or WriteAuthority.SUGGEST_ONLY.value).upper()
    try:
        return WriteAuthority(raw)
    except ValueError:
        return WriteAuthority.SUGGEST_ONLY


def get_break_even_config() -> BreakEvenConfig:
    policy = load_policy()
    raw = dict(policy.get("break_even") or {})
    return BreakEvenConfig(
        royalty_rate=float(raw.get("royalty_rate") or 0),
        margin_rate=float(raw.get("margin_rate") or 0),
        other_costs_pct=float(raw.get("other_costs_pct") or 0),
    )


def can_execute_write(*, approved: bool = False) -> tuple[bool, str]:
    authority = get_write_authority()
    if authority == WriteAuthority.SUGGEST_ONLY:
        if approved:
            return True, "approved override for SUGGEST_ONLY"
        return False, "write authority is SUGGEST_ONLY"
    if authority == WriteAuthority.EXECUTE_WITHIN_POLICY:
        if can_enqueue_executable_work(PROACTIVITY_EXECUTE_WITHIN_POLICY, approved=approved):
            return True, "EXECUTE_WITHIN_POLICY permits bounded writes"
        return False, "EXECUTE_WITHIN_POLICY requires approval or budget authorization"
    return False, f"unknown write authority: {authority.value}"


def is_protected_entity(entity_id: str) -> bool:
    policy = load_policy()
    protected = policy.get("protected_entities") or []
    return entity_id in protected


def validate_proposed_change(
    *,
    entity_id: str,
    action: str,
    before: dict[str, Any],
    after: dict[str, Any],
    evidence_days: int,
    projected_daily_spend: float | None = None,
) -> None:
    policy = load_policy()
    if is_protected_entity(entity_id):
        raise PolicyViolation(f"entity {entity_id} is protected")

    min_days = int(policy.get("min_evidence_days") or 7)
    if evidence_days < min_days:
        raise PolicyViolation(f"insufficient evidence: {evidence_days}d < {min_days}d minimum")

    max_bid_pct = float(policy.get("max_bid_change_pct") or 20.0)
    max_budget_pct = float(policy.get("max_budget_change_pct") or 15.0)
    spend_ceiling = float(policy.get("absolute_daily_spend_ceiling") or 500.0)

    if "bid" in before and "bid" in after:
        old_bid = float(before.get("bid") or 0)
        new_bid = float(after.get("bid") or 0)
        if old_bid > 0:
            pct = abs(new_bid - old_bid) / old_bid * 100
            if pct > max_bid_pct:
                raise PolicyViolation(f"bid change {pct:.1f}% exceeds cap {max_bid_pct}%")

    if "budget" in before and "budget" in after:
        old_budget = float(before.get("budget") or 0)
        new_budget = float(after.get("budget") or 0)
        if old_budget > 0:
            pct = abs(new_budget - old_budget) / old_budget * 100
            if pct > max_budget_pct:
                raise PolicyViolation(f"budget change {pct:.1f}% exceeds cap {max_budget_pct}%")

    if projected_daily_spend is not None and projected_daily_spend > spend_ceiling:
        raise PolicyViolation(
            f"projected daily spend {projected_daily_spend} exceeds ceiling {spend_ceiling}"
        )


def effective_proactivity_mode() -> str:
    authority = get_write_authority()
    if authority == WriteAuthority.EXECUTE_WITHIN_POLICY:
        return PROACTIVITY_EXECUTE_WITHIN_POLICY
    return PROACTIVITY_SUGGEST_ONLY
