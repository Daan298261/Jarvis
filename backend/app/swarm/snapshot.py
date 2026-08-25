"""Additive one-node swarm summary. Does not replace Node/role/budget control-plane modules."""

from __future__ import annotations

from typing import Any

from .nodes import list_nodes
from .roles import get_swarm_roles


def _enrich_worker(worker: dict[str, Any]) -> dict[str, Any]:
    status = str(worker.get("status") or "unknown")
    kind = str(worker.get("kind") or "worker")
    available = status in {"ready", "online", "loaded"}
    return {
        **worker,
        "available": available,
        "detail": worker.get("detail") or f"{kind} service on this node · {status}",
    }


async def swarm_snapshot() -> dict[str, Any]:
    """Control-plane view composed from current Node, role, and worker bindings.

    Orchestrator is this process. Leader is the strongest execution Node
    (localhost until a second machine exists). They are distinct roles even
    when they currently share a host.
    """
    nodes = await list_nodes()
    roles = await get_swarm_roles()
    local = next((node for node in nodes if node.get("is_local")), nodes[0] if nodes else None)
    workers = [_enrich_worker(item) for item in ((local or {}).get("workers") or [])]
    node_id = str((local or {}).get("id") or "")
    orchestrator = roles.get("orchestrator") if isinstance(roles, dict) else None
    leader = roles.get("leader") if isinstance(roles, dict) else None
    colocated = bool(
        orchestrator
        and leader
        and orchestrator.get("node_id")
        and orchestrator.get("node_id") == leader.get("node_id")
    )
    return {
        "mode": "one-node" if len(nodes) <= 1 else "multi-node",
        "orchestrator": {
            "role": "orchestrator",
            "kind": "control_plane",
            "node_id": (orchestrator or {}).get("node_id") or node_id,
            "hostname": (orchestrator or {}).get("hostname") or (local or {}).get("hostname") or "",
            "assignment": (orchestrator or {}).get("assignment"),
            "policy": (orchestrator or {}).get("policy"),
            "colocated_with_leader": colocated,
            "detail": (
                "This Jarvis process is the swarm control plane (scheduler, registry, "
                "verification). It is not the Leader execution role."
            ),
        },
        "leader": {
            "role": "leader",
            "node_id": (leader or {}).get("node_id") or node_id,
            "hostname": (leader or {}).get("hostname") or (local or {}).get("hostname") or "",
            "node_class": (local or {}).get("class") or "leader",
            "assignment": (leader or {}).get("assignment"),
            "policy": (leader or {}).get("policy"),
            "detail": (
                "Strongest general-purpose execution Node currently available. "
                "On a one-node swarm this is the local machine."
            ),
        },
        "nodes": nodes,
        "workers": workers,
    }
