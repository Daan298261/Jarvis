from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..swarm.nodes import get_node, list_nodes
from ..swarm.roles import get_swarm_roles

router = APIRouter(prefix="/api/swarm", tags=["swarm"])


@router.get("/roles")
async def swarm_roles():
    return await get_swarm_roles()


@router.get("/nodes")
async def swarm_nodes():
    nodes = await list_nodes()
    return {"nodes": nodes}


@router.get("/nodes/{node_id}")
async def swarm_node_detail(node_id: str):
    node = await get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    return node
