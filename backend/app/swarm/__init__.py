"""Swarm control-plane primitives: Nodes, roles, and placement (P2 foundation)."""

from .nodes import get_node, list_nodes, register_localhost_node

__all__ = ["get_node", "list_nodes", "register_localhost_node"]
