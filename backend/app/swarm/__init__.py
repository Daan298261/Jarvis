"""Swarm control-plane primitives: Nodes, roles, capabilities, and placement (P2 foundation)."""

from .capabilities import detect_localhost_capabilities, list_all_capabilities, register_localhost_capabilities
from .nodes import get_node, list_nodes, register_localhost_node
from .roles import get_swarm_roles
from .workers import bind_workers_to_node, worker_catalog

__all__ = [
    "bind_workers_to_node",
    "detect_localhost_capabilities",
    "get_node",
    "get_swarm_roles",
    "list_all_capabilities",
    "list_nodes",
    "register_localhost_capabilities",
    "register_localhost_node",
    "worker_catalog",
]
