"""Swarm control-plane primitives: Nodes, roles, capabilities, and placement (P2 foundation)."""

from .budgets import (
    acquire_lease,
    ensure_default_node_budget,
    get_node_budget,
    list_node_leases,
    release_lease,
    remaining_budget,
    set_node_budget,
)
from .capabilities import detect_localhost_capabilities, list_all_capabilities, register_localhost_capabilities
from .nodes import get_node, list_nodes, register_localhost_node
from .intelligence import dispatch_work, select_intelligence
from .placement import place_work
from .roles import get_swarm_roles
from .scoring import probe_node_warm_state, score_candidate
from .snapshot import swarm_snapshot
from .workers import bind_workers_to_node, worker_catalog

__all__ = [
    "acquire_lease",
    "bind_workers_to_node",
    "detect_localhost_capabilities",
    "ensure_default_node_budget",
    "get_node",
    "get_node_budget",
    "dispatch_work",
    "get_swarm_roles",
    "list_all_capabilities",
    "list_node_leases",
    "list_nodes",
    "place_work",
    "probe_node_warm_state",
    "register_localhost_capabilities",
    "score_candidate",
    "select_intelligence",
    "register_localhost_node",
    "release_lease",
    "remaining_budget",
    "set_node_budget",
    "swarm_snapshot",
    "worker_catalog",
]
