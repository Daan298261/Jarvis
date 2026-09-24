"""Computer-use targeting and RDP launch API (RFC-0079) + Reflex fast loop (RFC-0172)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..workers.computer import run_reflex_computer_use
from ..workers.computer_use_plan import isolate_device_plan, list_computer_targets, plan_computer_use, start_rdp_session

router = APIRouter(prefix="/api/computer-use", tags=["computer-use"])


class PlanBody(BaseModel):
    goal: str = Field(..., min_length=1, max_length=4000)
    preferred_node_id: str | None = None
    source: str | None = None


class RdpBody(BaseModel):
    host: str | None = None
    node_id: str | None = None


class IsolateBody(BaseModel):
    device: str = Field(..., min_length=1, max_length=200)
    reason: str = ""


class ReflexBody(BaseModel):
    goal: str = Field(..., min_length=1, max_length=4000)
    app: str | None = None
    nodes: list[dict[str, Any]] | None = None


@router.get("/targets")
async def computer_use_targets():
    return {"targets": await list_computer_targets()}


@router.post("/plan")
async def computer_use_plan(body: PlanBody):
    from ..policy.cyber_ato import license_blocks

    blocked = license_blocks("computer-use")
    if blocked:
        raise HTTPException(403, blocked)
    try:
        return await plan_computer_use(
            body.goal,
            preferred_node_id=body.preferred_node_id,
            source=body.source,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/rdp")
async def computer_use_rdp(body: RdpBody):
    try:
        return await start_rdp_session(host=body.host, node_id=body.node_id)
    except KeyError:
        raise HTTPException(404, "Node not found") from None
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(403, str(exc)) from exc


@router.post("/blue/isolate")
async def computer_use_blue_isolate(body: IsolateBody):
    try:
        plan = isolate_device_plan(device=body.device, reason=body.reason)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if plan["status"] == "deny":
        raise HTTPException(403, plan["reason"])
    return plan


@router.post("/reflex/run")
async def computer_use_reflex_run(body: ReflexBody):
    """RFC-0172 Reflex-first fast loop. Fail closed without ActionFrame / Reflex Lane."""
    from ..policy.cyber_ato import license_blocks

    blocked = license_blocks("computer-use")
    if blocked:
        raise HTTPException(403, blocked)
    result = await run_reflex_computer_use(body.goal, app=body.app, nodes=body.nodes)
    payload = {
        "success": result.success,
        "output": result.output,
        "error": result.error,
        "data": result.data,
    }
    if not result.success:
        # Honest refuse — not a soft 200 success.
        raise HTTPException(status_code=409, detail=payload)
    return payload


@router.get("/reflex/benchmark")
async def computer_use_reflex_benchmark():
    """Deterministic Reflex vs Anzu baseline metrics (RFC-0172 acceptance)."""
    from ..reflex_loop.runtime import run_reflex_benchmark

    return await run_reflex_benchmark()
