from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ResourceType = Literal["task", "agent", "project", "decision_inbox"]
GuestAction = Literal["read", "query", "approve"]

RESOURCE_TYPES: tuple[str, ...] = ("task", "agent", "project", "decision_inbox")
GUEST_ACTIONS: tuple[str, ...] = ("read", "query", "approve")

# Capabilities denied to every guest portal unless explicitly granted via scope grants.
DEFAULT_DENIED_CAPABILITIES: tuple[str, ...] = (
    "filesystem",
    "terminal",
    "settings",
    "admin",
    "mcp",
    "tools",
    "swarm",
    "license",
    "autonomy",
    "packs",
    "memory_write",
    "self_dev",
    "coding",
    "voice",
    "worker_environments",
    "runtime_profiles",
    "trajectories",
    "context_repo",
    "agent_portability",
    "delegation_spawn",
)


class ScopedGrant(BaseModel):
    resource_type: ResourceType
    resource_id: str
    actions: list[GuestAction] = Field(default_factory=list)


class PortalScope(BaseModel):
    grants: list[ScopedGrant] = Field(default_factory=list)


class PortalLimits(BaseModel):
    single_use: bool = False
    max_sessions: int | None = None
    max_uses: int | None = None


class PortalSession(BaseModel):
    session_id: str
    guest_label: str
    created_at: str
    last_seen_at: str


class PortalRecord(BaseModel):
    id: str
    label: str
    guest_label: str
    scope: PortalScope = Field(default_factory=PortalScope)
    limits: PortalLimits = Field(default_factory=PortalLimits)
    token_hash: str
    created_at: str
    expires_at: str | None = None
    revoked: bool = False
    revoked_at: str | None = None
    uses_remaining: int | None = None
    sessions: list[PortalSession] = Field(default_factory=list)


class EffectivePermissions(BaseModel):
    grants: list[ScopedGrant]
    denied_capabilities: list[str]
    allowed_actions_summary: dict[str, list[str]]
    limits: PortalLimits
    expires_at: str | None = None


class AuditEntry(BaseModel):
    id: str
    portal_id: str
    session_id: str
    guest_label: str
    action: str
    resource_type: str | None = None
    resource_id: str | None = None
    path: str | None = None
    outcome: str
    detail: str | None = None
    created_at: str


def scope_from_dict(raw: dict[str, Any] | None) -> PortalScope:
    if not raw:
        return PortalScope()
    grants_raw = raw.get("grants")
    if not isinstance(grants_raw, list):
        return PortalScope()
    grants: list[ScopedGrant] = []
    for item in grants_raw:
        if not isinstance(item, dict):
            continue
        resource_type = item.get("resource_type")
        resource_id = item.get("resource_id")
        if not resource_type or not resource_id:
            continue
        actions = [str(a) for a in item.get("actions") or []]
        grants.append(
            ScopedGrant(
                resource_type=resource_type,
                resource_id=str(resource_id),
                actions=actions,
            )
        )
    return PortalScope(grants=grants)
