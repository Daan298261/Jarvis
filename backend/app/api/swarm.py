from __future__ import annotations

from fastapi import APIRouter

from ..swarm import swarm_snapshot
from ..swarm.nodes import list_nodes
from ..swarm.workers import software_workers_on_nodes

router = APIRouter(prefix="/api/swarm", tags=["swarm"])


@router.get("")
async def swarm_overview():
    return await swarm_snapshot()


@router.get("/nodes")
async def swarm_nodes():
    return await list_nodes()


@router.get("/workers")
async def swarm_workers():
    nodes = await list_nodes()
    return software_workers_on_nodes(nodes)
