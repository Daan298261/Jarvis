from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from ..db.models import Node, SwarmRole
from ..db.session import SessionLocal

ROLE_ORCHESTRATOR = "orchestrator"
ROLE_LEADER = "leader"
SWARM_ROLES = (ROLE_ORCHESTRATOR, ROLE_LEADER)
ASSIGNMENT_FORCED = "FORCED"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def role_holder_dict(role: SwarmRole, node: Node | None) -> dict[str, Any]:
    return {
        "role": role.role,
        "node_id": role.node_id,
        "hostname": node.hostname if node else "",
        "assignment": role.assignment,
    }


async def ensure_localhost_role_assignments(node_id: str) -> list[SwarmRole]:
    """Assign Orchestrator and Leader roles to a node (FORCED one-node default)."""
    now = _utcnow()
    roles_json = json.dumps(list(SWARM_ROLES))
    async with SessionLocal() as session:
        node = await session.get(Node, node_id)
        if node is None:
            return []

        assigned: list[SwarmRole] = []
        for role_name in SWARM_ROLES:
            existing = await session.get(SwarmRole, role_name)
            if existing is not None:
                existing.node_id = node_id
                existing.assignment = ASSIGNMENT_FORCED
                existing.updated_at = now
                assigned.append(existing)
            else:
                record = SwarmRole(
                    role=role_name,
                    node_id=node_id,
                    assignment=ASSIGNMENT_FORCED,
                    updated_at=now,
                )
                session.add(record)
                assigned.append(record)

        node.roles_json = roles_json
        node.updated_at = now
        await session.commit()
        for record in assigned:
            await session.refresh(record)
        return assigned


async def get_swarm_roles() -> dict[str, Any]:
    """Return orchestrator and leader holders as distinct swarm-level role records."""
    async with SessionLocal() as session:
        role_rows = (await session.execute(select(SwarmRole))).scalars().all()
        nodes = (await session.execute(select(Node))).scalars().all()
        node_by_id = {row.id: row for row in nodes}

        payload: dict[str, Any] = {}
        for role_name in SWARM_ROLES:
            record = next((row for row in role_rows if row.role == role_name), None)
            if record is None:
                payload[role_name] = None
            else:
                payload[role_name] = role_holder_dict(record, node_by_id.get(record.node_id))
        return payload


async def list_role_records() -> list[SwarmRole]:
    async with SessionLocal() as session:
        return (await session.execute(select(SwarmRole).order_by(SwarmRole.role.asc()))).scalars().all()
