from __future__ import annotations

from dataclasses import dataclass

from ..tools.base import RiskLevel
from .inheritance import resolve_capability, resolve_effective_level
from .levels import AutonomyLevel, can_execute, parse_level
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
    arguments: dict | None = None,
    risk: RiskLevel = RiskLevel.MEDIUM,
    profile_id: str | None = None,
    approved: bool = False,
    agent_autonomy: dict[str, str] | None = None,
    platform_caps: dict[str, str] | None = None,
) -> AuthorizationResult:
    from .computer_permissions import evaluate_tool_permissions

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

    if not can_execute(effective):
        return AuthorizationResult(
            allowed=False,
            requires_approval=False,
            reason=f"effective autonomy {effective.value} does not permit tool execution",
            effective_level=effective,
            capability=capability,
        )

    perm = evaluate_tool_permissions(tool_name, arguments or ({"action": action} if action else {}))
    if perm.status == "deny":
        return AuthorizationResult(
            allowed=False,
            requires_approval=False,
            reason=perm.reason,
            effective_level=effective,
            capability=capability,
        )
    if perm.status == "ask" and not approved:
        return AuthorizationResult(
            allowed=False,
            requires_approval=True,
            reason=perm.reason,
            effective_level=effective,
            capability=capability,
        )

    if risk != RiskLevel.IRREVERSIBLE:
        return AuthorizationResult(
            allowed=True,
            requires_approval=False,
            reason="routine execution auto-approved by platform policy",
            effective_level=effective,
            capability=capability,
        )

    if approved:
        return AuthorizationResult(
            allowed=True,
            requires_approval=False,
            reason="destructive deletion explicitly approved",
            effective_level=effective,
            capability=capability,
        )
    return AuthorizationResult(
        allowed=False,
        requires_approval=True,
        reason="destructive deletion requires explicit approval",
        effective_level=effective,
        capability=capability,
    )
