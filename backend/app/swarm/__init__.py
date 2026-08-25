"""One-node swarm foundation: Node identity, software Workers, control-plane roles.

A Node is a machine. A Worker is a software service that runs on an eligible Node.
The Orchestrator is this control-plane process; the Leader is the strongest
execution Node (localhost while this is a one-node swarm).
"""

from .nodes import ensure_local_node, list_nodes, local_node_id, node_as_dict
from .snapshot import swarm_snapshot
from .workers import software_workers_on_nodes

__all__ = [
    "ensure_local_node",
    "list_nodes",
    "local_node_id",
    "node_as_dict",
    "software_workers_on_nodes",
    "swarm_snapshot",
]
