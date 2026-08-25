from __future__ import annotations

import json
import platform
import socket
import uuid
from typing import Any

from sqlalchemy import select

from ..config import data_dir
from ..db.models import SwarmNode, utcnow
from ..db.session import SessionLocal
from ..hardware import hardware_dict
from ..tools.capabilities import capability_snapshot


def local_node_id_path():
    return data_dir() / "node_id"


def local_node_id() -> str:
    """Stable identity for this machine. Survives database rebuilds."""
    path = local_node_id_path()
    if path.exists():
        existing = path.read_text(encoding="utf-8").strip()
        if existing:
            return existing
    node_id = str(uuid.uuid4())
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(node_id, encoding="utf-8")
    return node_id


def _hostname() -> str:
    try:
        return socket.gethostname() or platform.node() or "localhost"
    except Exception:
        return platform.node() or "localhost"


def _capability_ids() -> list[str]:
    snap = capability_snapshot()
    ids: list[str] = []
    for item in snap.get("all") or []:
        ident = item.get("id")
        if ident and ident not in ids:
            ids.append(str(ident))
    return ids


def node_as_dict(row: SwarmNode) -> dict[str, Any]:
    try:
        capabilities = json.loads(row.capabilities_json or "[]")
    except json.JSONDecodeError:
        capabilities = []
    try:
        roles = json.loads(row.roles_json or "[]")
    except json.JSONDecodeError:
        roles = []
    return {
        "id": row.id,
        "hostname": row.hostname,
        "display_name": row.display_name or row.hostname,
        "os_name": row.os_name,
        "architecture": row.architecture,
        "status": row.status,
        "node_class": row.node_class,
        "is_local": bool(row.is_local),
        "capabilities": capabilities,
        "roles": roles,
        "last_seen_at": row.last_seen_at.isoformat() if row.last_seen_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


async def ensure_local_node() -> dict[str, Any]:
    """Create or refresh the localhost Node. One-node swarm: this machine is Leader."""
    node_id = local_node_id()
    hw = hardware_dict()
    hostname = _hostname()
    now = utcnow()
    payload = {
        "hostname": hostname,
        "display_name": hostname,
        "os_name": str(hw.get("os_name") or platform.system()),
        "architecture": str(hw.get("architecture") or platform.machine()),
        "status": "online",
        "node_class": "leader",
        "is_local": True,
        "capabilities_json": json.dumps(_capability_ids()),
        "roles_json": json.dumps(["orchestrator", "leader"]),
        "last_seen_at": now,
        "updated_at": now,
    }
    async with SessionLocal() as session:
        row = await session.get(SwarmNode, node_id)
        if row is None:
            local = (
                await session.execute(select(SwarmNode).where(SwarmNode.is_local.is_(True)))
            ).scalars().first()
            if local is not None:
                row = local
                local_node_id_path().write_text(row.id, encoding="utf-8")
            else:
                row = SwarmNode(id=node_id, created_at=now)
                session.add(row)
        for key, value in payload.items():
            setattr(row, key, value)
        await session.commit()
        await session.refresh(row)
        return node_as_dict(row)


async def list_nodes() -> list[dict[str, Any]]:
    await ensure_local_node()
    async with SessionLocal() as session:
        rows = (await session.execute(select(SwarmNode).order_by(SwarmNode.created_at))).scalars().all()
    return [node_as_dict(row) for row in rows]
