from __future__ import annotations

from typing import Any

from .schema import (
    DEFAULT_DENIED_CAPABILITIES,
    EffectivePermissions,
    GuestAction,
    PortalLimits,
    PortalScope,
    ResourceType,
    ScopedGrant,
)


def build_effective_permissions(
    scope: PortalScope,
    limits: PortalLimits,
    expires_at: str | None = None,
) -> EffectivePermissions:
    summary: dict[str, list[str]] = {}
    for grant in scope.grants:
        key = f"{grant.resource_type}:{grant.resource_id}"
        summary[key] = sorted(set(grant.actions))
    return EffectivePermissions(
        grants=list(scope.grants),
        denied_capabilities=list(DEFAULT_DENIED_CAPABILITIES),
        allowed_actions_summary=summary,
        limits=limits,
        expires_at=expires_at,
    )


def _grant_matches(grant: ScopedGrant, resource_type: ResourceType, resource_id: str) -> bool:
    if grant.resource_type != resource_type:
        return False
    if grant.resource_id == "*":
        return True
    return grant.resource_id == resource_id


def is_action_granted(scope: PortalScope, resource_type: ResourceType, resource_id: str, action: GuestAction) -> bool:
    for grant in scope.grants:
        if _grant_matches(grant, resource_type, resource_id) and action in grant.actions:
            return True
    return False


def can_access_resource(scope: PortalScope, resource_type: ResourceType, resource_id: str) -> bool:
    for grant in scope.grants:
        if _grant_matches(grant, resource_type, resource_id):
            return True
    return False


def preview_scope(scope: PortalScope, limits: PortalLimits, expires_at: str | None = None) -> dict[str, Any]:
    effective = build_effective_permissions(scope, limits, expires_at)
    return effective.model_dump()
