from __future__ import annotations

from dataclasses import dataclass

from ..tools.base import RiskLevel
from .inheritance import resolve_capability, resolve_effective_level
from .levels import AutonomyLevel, LEVEL_RANK, can_execute, parse_level
from .store import get_agent_autonomy_map, get_platform_autonomy_caps, get_platform_policy


@dataclass
class AuthorizationResult:
    allowed: bool
    requires_approval: bool
    reason: str
    effective_level: AutonomyLevel
    capability: str

    def as_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "requires_approval": self.requires_approval,
            "reason": self.reason,
            "effective_level": self.effective_level.value,
            "capability": self.capability,
        }


def authorize(
    tool_name: str,
    *,
    action: str | None = None,
    risk: RiskLevel = RiskLevel.MEDIUM,
    profile_id: str | None = None,
    approved: bool = False,
    agent_autonomy: dict[str, str] | None = None,
    platform_caps: dict[str, str] | None = None,
) -> AuthorizationResult:
    capability = resolve_capability(tool_name, action)
    platform = get_platform_policy()
    default_agent = parse_level(platform.get("default_agent_autonomy"))
    agent_levels = agent_autonomy if agent_autonomy is not None else get_agent_autonomy_map(profile_id)
    platform_levels = platform_caps if platform_caps is not None else get_platform_autonomy_caps()
    effective = resolve_effective_level(
        capability,
        agent_levels,
        platform_levels,
        default_agent=default_agent,
    )
    rank = LEVEL_RANK[effective]

    if not can_execute(effective):
        return AuthorizationResult(
            allowed=False,
            requires_approval=False,
            reason=f"effective autonomy {effective.value} does not permit tool execution",
            effective_level=effective,
            capability=capability,
        )

    if risk == RiskLevel.LOW:
        allowed = rank >= LEVEL_RANK[AutonomyLevel.L2_EXECUTE_SAFE]
        return AuthorizationResult(
            allowed=allowed,
            requires_approval=False,
            reason="low-risk execution permitted" if allowed else "insufficient autonomy for low-risk execution",
            effective_level=effective,
            capability=capability,
        )

    if risk == RiskLevel.MEDIUM:
        allowed = rank >= LEVEL_RANK[AutonomyLevel.L3_EXECUTE_WITH_GATES]
        return AuthorizationResult(
            allowed=allowed,
            requires_approval=False,
            reason="medium-risk execution permitted" if allowed else "insufficient autonomy for medium-risk execution",
            effective_level=effective,
            capability=capability,
        )

    if risk == RiskLevel.HIGH:
        if rank >= LEVEL_RANK[AutonomyLevel.L4_AUTONOMOUS]:
            return AuthorizationResult(
                allowed=True,
                requires_approval=False,
                reason="high-risk execution permitted",
                effective_level=effective,
                capability=capability,
            )
        if rank == LEVEL_RANK[AutonomyLevel.L3_EXECUTE_WITH_GATES]:
            if approved:
                return AuthorizationResult(
                    allowed=True,
                    requires_approval=False,
                    reason="approved high-risk execution",
                    effective_level=effective,
                    capability=capability,
                )
            return AuthorizationResult(
                allowed=False,
                requires_approval=True,
                reason="high-risk action requires approval at L3_EXECUTE_WITH_GATES",
                effective_level=effective,
                capability=capability,
            )
        return AuthorizationResult(
            allowed=False,
            requires_approval=False,
            reason="insufficient autonomy for high-risk execution",
            effective_level=effective,
            capability=capability,
        )

    # IRREVERSIBLE
    if rank >= LEVEL_RANK[AutonomyLevel.L5_OPERATOR]:
        return AuthorizationResult(
            allowed=True,
            requires_approval=False,
            reason="irreversible execution permitted for operator",
            effective_level=effective,
            capability=capability,
        )
    if rank == LEVEL_RANK[AutonomyLevel.L4_AUTONOMOUS]:
        if approved:
            return AuthorizationResult(
                allowed=True,
                requires_approval=False,
                reason="approved irreversible execution",
                effective_level=effective,
                capability=capability,
            )
        return AuthorizationResult(
            allowed=False,
            requires_approval=True,
            reason="irreversible action requires approval at L4_AUTONOMOUS",
            effective_level=effective,
            capability=capability,
        )
    return AuthorizationResult(
        allowed=False,
        requires_approval=False,
        reason="insufficient autonomy for irreversible execution",
        effective_level=effective,
        capability=capability,
    )
