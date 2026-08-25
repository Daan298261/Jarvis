from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select

from ..db.models import Node, NodeRolePolicy, SwarmRole
from ..db.session import SessionLocal

ROLE_ORCHESTRATOR = "orchestrator"
ROLE_LEADER = "leader"
SWARM_ROLES = (ROLE_ORCHESTRATOR, ROLE_LEADER)

ASSIGNMENT_AUTO = "AUTO"
ASSIGNMENT_PREFERRED = "PREFERRED"
ASSIGNMENT_FORCED = "FORCED"
ASSIGNMENT_AVOID = "AVOID"
ASSIGNMENT_DISABLED = "DISABLED"

ROLE_POLICIES = (
    ASSIGNMENT_AUTO,
    ASSIGNMENT_PREFERRED,
    ASSIGNMENT_FORCED,
    ASSIGNMENT_AVOID,
    ASSIGNMENT_DISABLED,
)
DEFAULT_LOCALHOST_POLICY = ASSIGNMENT_FORCED


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalize_policy(policy: str) -> str:
    return str(policy or "").strip().upper()


def validate_policy(policy: str) -> str:
    normalized = normalize_policy(policy)
    if normalized not in ROLE_POLICIES:
        raise ValueError(f"Invalid role policy: {policy!r}")
    return normalized


def is_eligible_for_role(policy: str, *, necessary: bool = False) -> bool:
    """Return whether a node with this policy may hold the role."""
    normalized = validate_policy(policy)
    if normalized == ASSIGNMENT_DISABLED:
        return False
    if normalized == ASSIGNMENT_AVOID:
        return necessary
    return True


def must_hold_role(policy: str) -> bool:
    """Return whether a node with this policy must hold the role while online."""
    return normalize_policy(policy) == ASSIGNMENT_FORCED


def role_holder_dict(
    role: SwarmRole,
    node: Node | None,
    *,
    policy: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "role": role.role,
        "node_id": role.node_id,
        "hostname": node.hostname if node else "",
        "assignment": role.assignment,
    }
    if policy is not None:
        payload["policy"] = policy
    return payload


async def _node_count(session) -> int:
    return (await session.execute(select(func.count()).select_from(Node))).scalar_one()


async def ensure_default_role_policies(node_id: str) -> list[NodeRolePolicy]:
    """Create FORCED policies for localhost roles only when no row exists yet."""
    now = _utcnow()
    created: list[NodeRolePolicy] = []
    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            return []

        for role_name in SWARM_ROLES:
            existing = (
                await session.execute(
                    select(NodeRolePolicy).where(
                        NodeRolePolicy.node_id == node_id,
                        NodeRolePolicy.role == role_name,
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                continue
            record = NodeRolePolicy(
                node_id=node_id,
                role=role_name,
                policy=DEFAULT_LOCALHOST_POLICY,
                updated_at=now,
            )
            session.add(record)
            created.append(record)

        if created:
            await session.commit()
            for record in created:
                await session.refresh(record)
    return created


async def get_node_role_policies(node_id: str) -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            return []
        rows = (
            await session.execute(
                select(NodeRolePolicy)
                .where(NodeRolePolicy.node_id == node_id)
                .order_by(NodeRolePolicy.role.asc())
            )
        ).scalars().all()
        return [
            {
                "node_id": row.node_id,
                "role": row.role,
                "policy": row.policy,
                "updated_at": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in rows
        ]


async def get_node_role_policy(node_id: str, role: str) -> str | None:
    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(NodeRolePolicy).where(
                    NodeRolePolicy.node_id == node_id,
                    NodeRolePolicy.role == role,
                )
            )
        ).scalar_one_or_none()
        return row.policy if row else None


async def set_node_role_policy(node_id: str, role: str, policy: str) -> dict[str, Any]:
    normalized_role = str(role or "").strip().lower()
    if normalized_role not in SWARM_ROLES:
        raise ValueError(f"Unknown swarm role: {role!r}")
    normalized_policy = validate_policy(policy)
    now = _utcnow()

    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            raise LookupError("Node not found")

        row = (
            await session.execute(
                select(NodeRolePolicy).where(
                    NodeRolePolicy.node_id == node_id,
                    NodeRolePolicy.role == normalized_role,
                )
            )
        ).scalar_one_or_none()
        if row is None:
            row = NodeRolePolicy(
                node_id=node_id,
                role=normalized_role,
                policy=normalized_policy,
                updated_at=now,
            )
            session.add(row)
        else:
            row.policy = normalized_policy
            row.updated_at = now
        await session.commit()
        await session.refresh(row)

    await sync_role_holders_for_node(node_id)
    return {
        "node_id": row.node_id,
        "role": row.role,
        "policy": row.policy,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def sync_role_holders_for_node(node_id: str) -> list[SwarmRole]:
    """Apply per-node role policies to SwarmRole holders and node.roles_json."""
    now = _utcnow()
    assigned: list[SwarmRole] = []

    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            return []

        node_count = await _node_count(session)
        necessary = node_count <= 1

        policy_rows = (
            await session.execute(
                select(NodeRolePolicy).where(NodeRolePolicy.node_id == node_id)
            )
        ).scalars().all()
        policies = {row.role: row.policy for row in policy_rows}

        held_roles: list[str] = []
        for role_name in SWARM_ROLES:
            policy = policies.get(role_name, DEFAULT_LOCALHOST_POLICY)
            eligible = is_eligible_for_role(policy, necessary=necessary)
            required = must_hold_role(policy)

            existing = await session.get(SwarmRole, role_name)
            if eligible or required:
                if existing is None:
                    existing = SwarmRole(
                        role=role_name,
                        node_id=node_id,
                        assignment=policy,
                        updated_at=now,
                    )
                    session.add(existing)
                else:
                    existing.node_id = node_id
                    existing.assignment = policy
                    existing.updated_at = now
                held_roles.append(role_name)
                assigned.append(existing)
            elif existing is not None and existing.node_id == node_id:
                existing.node_id = None
                existing.assignment = policy
                existing.updated_at = now
                assigned.append(existing)

        node.roles_json = json.dumps(held_roles)
        node.updated_at = now
        await session.commit()
        for record in assigned:
            await session.refresh(record)
        return assigned


async def ensure_localhost_role_assignments(node_id: str) -> list[SwarmRole]:
    """Ensure default policies exist, then sync holders for the localhost node."""
    await ensure_default_role_policies(node_id)
    return await sync_role_holders_for_node(node_id)


async def get_swarm_roles() -> dict[str, Any]:
    """Return orchestrator and leader holders as distinct swarm-level role records."""
    async with SessionLocal() as session:
        role_rows = (await session.execute(select(SwarmRole))).scalars().all()
        nodes = (await session.execute(select(Node))).scalars().all()
        policy_rows = (await session.execute(select(NodeRolePolicy))).scalars().all()
        node_by_id = {row.id: row for row in nodes}
        policy_by_node_role = {(row.node_id, row.role): row.policy for row in policy_rows}

        payload: dict[str, Any] = {}
        for role_name in SWARM_ROLES:
            record = next((row for row in role_rows if row.role == role_name), None)
            if record is None or record.node_id is None:
                payload[role_name] = None
                continue
            holder_policy = policy_by_node_role.get((record.node_id, role_name))
            payload[role_name] = role_holder_dict(
                record,
                node_by_id.get(record.node_id),
                policy=holder_policy,
            )
        return payload


async def list_role_records() -> list[SwarmRole]:
    async with SessionLocal() as session:
        return (await session.execute(select(SwarmRole).order_by(SwarmRole.role.asc()))).scalars().all()
