from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..swarm.capabilities import list_all_capabilities
from ..swarm.nodes import get_node, list_nodes
from ..swarm.roles import (
    SWARM_ROLES,
    get_node_role_policies,
    get_swarm_roles,
    set_node_role_policy,
)

router = APIRouter(prefix="/api/swarm", tags=["swarm"])


class RolePolicyUpdate(BaseModel):
    policy: str


@router.get("/roles")
async def swarm_roles():
    return await get_swarm_roles()


@router.get("/nodes/{node_id}/role-policies")
async def swarm_node_role_policies(node_id: str):
    node = await get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    policies = await get_node_role_policies(node_id)
    return {"node_id": node_id, "policies": policies}


@router.put("/nodes/{node_id}/role-policies/{role}")
async def swarm_put_node_role_policy(node_id: str, role: str, body: RolePolicyUpdate):
    node = await get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    if role.strip().lower() not in SWARM_ROLES:
        raise HTTPException(400, f"Unknown swarm role: {role}")
    try:
        updated = await set_node_role_policy(node_id, role, body.policy)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return updated


@router.get("/capabilities")
async def swarm_capabilities():
    capabilities = await list_all_capabilities()
    return {"capabilities": capabilities}


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
