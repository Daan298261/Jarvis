from __future__ import annotations

from typing import Any

from ..agent.acp import acp_status
from ..agent.coding_workers import coding_worker_catalog
from ..tools.capabilities import native_capabilities, optional_workers

# Native capabilities that are software execution services, not the Node itself.
_NATIVE_WORKER_IDS = {"playwright", "windows_ui", "voice"}


def _place(item: dict[str, Any], node_id: str, kind: str) -> dict[str, Any]:
    ident = str(item.get("id") or "")
    return {
        "id": ident,
        "name": item.get("name") or ident,
        "kind": item.get("kind") or kind,
        "status": item.get("status") or "unknown",
        "available": bool(item.get("available")),
        "detail": item.get("detail") or "",
        "node_id": node_id,
        "eligible_node_ids": [node_id],
        "service": True,
    }


def software_workers_on_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Advertise software Workers as services on eligible Nodes.

    On a one-node swarm every local worker is eligible on localhost. Missing
    optional packages stay listed with status=missing instead of disappearing.
    Workers are never Nodes.
    """
    local = next((node for node in nodes if node.get("is_local")), nodes[0] if nodes else None)
    if not local:
        return []
    node_id = local["id"]
    placed: list[dict[str, Any]] = []
    seen: set[str] = set()

    def add(item: dict[str, Any], kind: str) -> None:
        ident = str(item.get("id") or "")
        if not ident or ident in seen:
            return
        seen.add(ident)
        placed.append(_place(item, node_id, kind))

    for item in optional_workers():
        add(item, "optional")
    for item in coding_worker_catalog():
        add(item, "coding")
    add(acp_status(), "coding")
    for item in native_capabilities():
        if item.get("id") in _NATIVE_WORKER_IDS:
            add(item, "native")
    return placed
