from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from ..swarm.budgets import (
    acquire_lease,
    get_node_budget,
    list_node_leases,
    release_lease,
    set_node_budget,
)
from ..swarm.capabilities import list_all_capabilities
from ..swarm.nodes import get_node, list_nodes
from ..swarm.intelligence import dispatch_work, select_intelligence
from ..swarm.placement import place_work
from ..swarm.roles import (
    SWARM_ROLES,
    get_node_role_policies,
    get_swarm_roles,
    set_node_role_policy,
)
from ..swarm.snapshot import swarm_snapshot

router = APIRouter(prefix="/api/swarm", tags=["swarm"])


@router.get("")
async def swarm_overview():
    """Additive summary of Orchestrator vs Leader plus Node/worker bindings."""
    return await swarm_snapshot()


class RolePolicyUpdate(BaseModel):
    policy: str


class BudgetUpdate(BaseModel):
    preset: str | None = None
    mode: str | None = None
    global_percent: int | None = None
    limits: dict | None = None


class LeaseCreate(BaseModel):
    claim: dict = Field(default_factory=dict)
    ttl_seconds: int | None = 300


class PlacementRequest(BaseModel):
    capabilities: list[str] = Field(default_factory=list)
    role: str | None = None
    worker_id: str | None = None
    worker_kind: str | None = None
    claim: dict | None = None
    ttl_seconds: int | None = 300


class IntelligenceRequest(BaseModel):
    prompt: str
    task_class: str | None = None
    execution_mode: str | None = None


class DispatchRequest(BaseModel):
    prompt: str
    task_class: str | None = None
    execution_mode: str | None = None
    role: str | None = None
    claim: dict | None = None
    ttl_seconds: int | None = 300


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


@router.get("/nodes/{node_id}/budget")
async def swarm_get_node_budget(node_id: str):
    node = await get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    budget = await get_node_budget(node_id)
    if budget is None:
        raise HTTPException(404, "Node budget not found")
    return budget


@router.put("/nodes/{node_id}/budget")
async def swarm_put_node_budget(node_id: str, body: BudgetUpdate):
    node = await get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    payload = body.model_dump(exclude_unset=True)
    try:
        return await set_node_budget(node_id, payload)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/nodes/{node_id}/leases")
async def swarm_list_node_leases(node_id: str):
    node = await get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    leases = await list_node_leases(node_id)
    return {"node_id": node_id, "leases": leases}


@router.post("/nodes/{node_id}/leases")
async def swarm_create_node_lease(node_id: str, body: LeaseCreate):
    node = await get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    try:
        lease = await acquire_lease(node_id, body.claim, ttl_seconds=body.ttl_seconds)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return lease


@router.delete("/nodes/{node_id}/leases/{lease_id}")
async def swarm_delete_node_lease(node_id: str, lease_id: str):
    node = await get_node(node_id)
    if not node:
        raise HTTPException(404, "Node not found")
    try:
        return await release_lease(node_id, lease_id)
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/intelligence")
async def swarm_intelligence(body: IntelligenceRequest):
    return select_intelligence(
        body.prompt,
        task_class=body.task_class,
        execution_mode=body.execution_mode,
    )


@router.post("/dispatch")
async def swarm_dispatch(body: DispatchRequest):
    result = await dispatch_work(
        body.prompt,
        task_class=body.task_class,
        execution_mode=body.execution_mode,
        role=body.role,
        claim=body.claim,
        ttl_seconds=body.ttl_seconds,
    )
    placement = result["placement"]
    if not placement.get("accepted"):
        code = placement.get("code")
        if code in {"invalid_request", "invalid_role"}:
            raise HTTPException(400, placement.get("reason") or "Invalid dispatch request")
        return JSONResponse(status_code=409, content=result)
    return result


@router.post("/placement")
async def swarm_placement(body: PlacementRequest):
    result = await place_work(body.model_dump(exclude_unset=True))
    if not result.get("accepted"):
        code = result.get("code")
        if code in {"invalid_request", "invalid_role"}:
            raise HTTPException(400, result.get("reason") or "Invalid placement request")
        return JSONResponse(status_code=409, content=result)
    return result
