"""Versioned agent context repositories and idle-time memory consolidation."""

from .consolidation import consolidate_agent, eligible_trajectories
from .repository import (
    ContextRepoError,
    add_entry,
    delete_entry,
    diff_versions,
    get_entry,
    get_entry_permissions,
    get_repo,
    get_version,
    list_history,
    list_versions,
    pin_entry,
    revert_mutation,
)
from .scheduler import rank_nodes_for_consolidation, score_consolidation_node

__all__ = [
    "ContextRepoError",
    "add_entry",
    "consolidate_agent",
    "delete_entry",
    "diff_versions",
    "eligible_trajectories",
    "get_entry",
    "get_entry_permissions",
    "get_repo",
    "get_version",
    "list_history",
    "list_versions",
    "pin_entry",
    "rank_nodes_for_consolidation",
    "revert_mutation",
    "score_consolidation_node",
]
