"""Computer-use targeting and RDP launch API (RFC-0079)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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


@router.get("/targets")
async def computer_use_targets():
    return {"targets": await list_computer_targets()}


@router.post("/plan")
async def computer_use_plan(body: PlanBody):
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
