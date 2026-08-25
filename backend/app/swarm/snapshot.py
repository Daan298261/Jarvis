from __future__ import annotations

from typing import Any

from .nodes import list_nodes
from .workers import software_workers_on_nodes


async def swarm_snapshot() -> dict[str, Any]:
    """Control-plane view of the one-node swarm.

    Orchestrator is this process. Leader is the strongest execution Node
    (localhost until a second machine exists). They are distinct roles even
    when they currently share a host.
    """
    nodes = await list_nodes()
    local = next((node for node in nodes if node.get("is_local")), nodes[0] if nodes else None)
    workers = software_workers_on_nodes(nodes)
    node_id = local["id"] if local else ""
    return {
        "mode": "one-node",
        "orchestrator": {
            "role": "orchestrator",
            "kind": "control_plane",
            "node_id": node_id,
            "colocated_with_leader": True,
            "detail": (
                "This Jarvis process is the swarm control plane (scheduler, registry, "
                "verification). It is not the Leader execution role."
            ),
        },
        "leader": {
            "role": "leader",
            "node_id": node_id,
            "hostname": (local or {}).get("hostname") or "",
            "node_class": (local or {}).get("node_class") or "leader",
            "detail": (
                "Strongest general-purpose execution Node currently available. "
                "On a one-node swarm this is the local machine."
            ),
        },
        "nodes": nodes,
        "workers": workers,
    }
