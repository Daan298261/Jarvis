"""Swarm control-plane primitives: Nodes, roles, and placement (P2 foundation)."""

from .nodes import get_node, list_nodes, register_localhost_node
from .workers import bind_workers_to_node, worker_catalog

__all__ = ["bind_workers_to_node", "get_node", "list_nodes", "register_localhost_node", "worker_catalog"]
