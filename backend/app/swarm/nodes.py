from __future__ import annotations

import json
import socket
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import or_, select

from ..config import data_dir
from ..db.models import Node, NodeCapability, NodeWorker
from ..db.session import SessionLocal
from ..hardware import hardware_dict
from .roles import ensure_localhost_role_assignments

LOCALHOST_ALIAS = "localhost"
LOCALHOST_ADDRESS = "127.0.0.1"
LOCAL_NODE_IDENTITY_FILE = "node_identity.json"
DEFAULT_NODE_CLASS = "senior_worker"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def identity_path() -> Any:
    return data_dir() / LOCAL_NODE_IDENTITY_FILE


def _load_identity() -> dict[str, Any]:
    path = identity_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_identity(node_id: str) -> None:
    path = identity_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"node_id": node_id}, indent=2) + "\n", encoding="utf-8")


def load_or_create_local_node_id() -> str:
    payload = _load_identity()
    node_id = str(payload.get("node_id") or "").strip()
    if node_id:
        return node_id
    node_id = str(uuid.uuid4())
    _save_identity(node_id)
    return node_id


def default_resources(hardware: dict[str, Any]) -> dict[str, Any]:
    return {
        "cpu_cores": hardware.get("cpu_cores", 1),
        "cpu_threads": hardware.get("cpu_threads", 1),
        "ram_total_gb": hardware.get("ram_total_gb", 0),
        "ram_available_gb": hardware.get("ram_available_gb", 0),
        "vram_total_mib": hardware.get("vram_total_mib"),
        "vram_free_mib": hardware.get("vram_free_mib"),
        "disk_total_gb": hardware.get("disk_total_gb", 0),
        "disk_free_gb": hardware.get("disk_free_gb", 0),
        "gpu_name": hardware.get("gpu_name"),
    }


def node_to_dict(
    node: Node,
    workers: list[dict[str, Any]] | None = None,
    capabilities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    try:
        roles = json.loads(node.roles_json or "[]")
    except Exception:
        roles = []
    if not isinstance(roles, list):
        roles = []
    try:
        hardware = json.loads(node.hardware_json or "{}")
    except Exception:
        hardware = {}
    if not isinstance(hardware, dict):
        hardware = {}
    try:
        resources = json.loads(node.resources_json or "{}")
    except Exception:
        resources = {}
    if not isinstance(resources, dict):
        resources = {}
    return {
        "id": node.id,
        "hostname": node.hostname,
        "status": node.status,
        "class": node.node_class,
        "roles": roles,
        "address": node.address,
        "host_alias": node.host_alias,
        "is_local": node.is_local,
        "hardware": hardware,
        "resources": resources,
        "workers": workers if workers is not None else [],
        "capabilities": capabilities if capabilities is not None else [],
        "created_at": node.created_at.isoformat() if node.created_at else None,
        "updated_at": node.updated_at.isoformat() if node.updated_at else None,
        "last_seen_at": node.last_seen_at.isoformat() if node.last_seen_at else None,
    }


async def register_localhost_node() -> Node:
    """Register or refresh this process's machine as the localhost Node."""
    node_id = load_or_create_local_node_id()
    hardware = hardware_dict()
    resources = default_resources(hardware)
    hostname = socket.gethostname() or "localhost"
    now = _utcnow()
    hardware_json = json.dumps(hardware)
    resources_json = json.dumps(resources)

    async with SessionLocal() as session:
        existing = (
            await session.execute(
                select(Node).where(
                    or_(
                        Node.id == node_id,
                        Node.host_alias == LOCALHOST_ALIAS,
                        Node.address == LOCALHOST_ADDRESS,
                    )
                )
            )
        ).scalars().first()

        if existing is not None:
            if existing.id != node_id:
                _save_identity(existing.id)
                node_id = existing.id
            existing.hostname = hostname
            existing.status = "online"
            existing.node_class = DEFAULT_NODE_CLASS
            existing.address = LOCALHOST_ADDRESS
            existing.host_alias = LOCALHOST_ALIAS
            existing.hardware_json = hardware_json
            existing.resources_json = resources_json
            existing.is_local = True
            existing.updated_at = now
            existing.last_seen_at = now
            await session.commit()
            await session.refresh(existing)
            await ensure_localhost_role_assignments(existing.id)
            return existing

        node = Node(
            id=node_id,
            hostname=hostname,
            status="online",
            node_class=DEFAULT_NODE_CLASS,
            roles_json="[]",
            address=LOCALHOST_ADDRESS,
            host_alias=LOCALHOST_ALIAS,
            hardware_json=hardware_json,
            resources_json=resources_json,
            is_local=True,
            created_at=now,
            updated_at=now,
            last_seen_at=now,
        )
        session.add(node)
        await session.commit()
        await session.refresh(node)
        await ensure_localhost_role_assignments(node.id)
        return node


async def list_nodes() -> list[dict[str, Any]]:
    async with SessionLocal() as session:
        rows = (await session.execute(select(Node).order_by(Node.created_at.asc()))).scalars().all()
        if not rows:
            return []
        node_ids = [row.id for row in rows]
        worker_rows = (
            await session.execute(
                select(NodeWorker)
                .where(NodeWorker.node_id.in_(node_ids))
                .order_by(NodeWorker.worker_id.asc())
            )
        ).scalars().all()
        capability_rows = (
            await session.execute(
                select(NodeCapability)
                .where(NodeCapability.node_id.in_(node_ids))
                .order_by(NodeCapability.capability_id.asc())
            )
        ).scalars().all()
        workers_by_node: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in node_ids}
        capabilities_by_node: dict[str, list[dict[str, Any]]] = {node_id: [] for node_id in node_ids}
        for binding in worker_rows:
            workers_by_node.setdefault(binding.node_id, []).append(
                {
                    "id": binding.worker_id,
                    "name": binding.name,
                    "kind": binding.kind,
                    "status": binding.status,
                    "node_id": binding.node_id,
                }
            )
        for binding in capability_rows:
            capabilities_by_node.setdefault(binding.node_id, []).append(
                {
                    "id": binding.capability_id,
                    "name": binding.name,
                    "status": binding.status,
                    "detail": binding.detail,
                    "node_id": binding.node_id,
                }
            )
        return [
            node_to_dict(
                row,
                workers_by_node.get(row.id, []),
                capabilities_by_node.get(row.id, []),
            )
            for row in rows
        ]


async def get_node(node_id: str) -> dict[str, Any] | None:
    async with SessionLocal() as session:
        row = (await session.execute(select(Node).where(Node.id == node_id))).scalar_one_or_none()
        if not row:
            return None
        worker_rows = (
            await session.execute(
                select(NodeWorker)
                .where(NodeWorker.node_id == node_id)
                .order_by(NodeWorker.worker_id.asc())
            )
        ).scalars().all()
        capability_rows = (
            await session.execute(
                select(NodeCapability)
                .where(NodeCapability.node_id == node_id)
                .order_by(NodeCapability.capability_id.asc())
            )
        ).scalars().all()
        workers = [
            {
                "id": binding.worker_id,
                "name": binding.name,
                "kind": binding.kind,
                "status": binding.status,
                "node_id": binding.node_id,
            }
            for binding in worker_rows
        ]
        capabilities = [
            {
                "id": binding.capability_id,
                "name": binding.name,
                "status": binding.status,
                "detail": binding.detail,
                "node_id": binding.node_id,
            }
            for binding in capability_rows
        ]
        return node_to_dict(row, workers, capabilities)
