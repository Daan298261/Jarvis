from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agent.acp import ACP_WORKER, acp_status, handle_blocking_request, list_acp_sessions
from ..agent.coding_workers import coding_worker_catalog
from ..agent.escalation import get_escalation_package, list_escalation_packages
from ..coding.catalog import probe_cursor_models
from ..coding.routing import recommend_worker, workers_snapshot
from ..mcp_server import SERVER, jarvis_mcp_manifest

router = APIRouter(prefix="/api/coding", tags=["coding"])


class McpCallIn(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class AcpConnectIn(BaseModel):
    cwd: str | None = None
    model: str = "composer-2.5"
    session_id: str | None = None


class AcpAnswerIn(BaseModel):
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    isolated: bool = True
    autonomy: str = "autonomous"


class RouteIn(BaseModel):
    prompt: str
    task_class: str = "software engineering"


@router.get("")
async def coding_overview():
    probe = probe_cursor_models()
    return {
        "workers": workers_snapshot(),
        "catalog": coding_worker_catalog(),
        **probe,
    }


@router.get("/models")
async def coding_models():
    return probe_cursor_models()


@router.post("/route")
async def coding_route(body: RouteIn):
    rec = await recommend_worker(body.prompt, body.task_class)
    return {
        "worker": rec.worker,
        "model": rec.model,
        "tier": rec.tier,
        "complexity": rec.complexity,
        "reason": rec.reason,
        "paid": rec.paid,
        "fallback": rec.fallback,
        "historical": rec.historical,
    }


@router.get("/mcp")
async def jarvis_mcp():
    return jarvis_mcp_manifest()


@router.post("/mcp/call")
async def jarvis_mcp_call(body: McpCallIn):
    return await SERVER.call_tool(body.name, body.arguments)


@router.get("/escalations")
async def escalations():
    return await list_escalation_packages()


@router.get("/escalations/{package_id}")
async def escalation_detail(package_id: str):
    payload = await get_escalation_package(package_id)
    if not payload:
        raise HTTPException(404, "Escalation package not found")
    return payload


@router.get("/acp")
async def acp_info():
    info = acp_status()
    info["sessions"] = await list_acp_sessions()
    return info


@router.post("/acp/connect")
async def acp_connect(body: AcpConnectIn):
    initialized = await ACP_WORKER.initialize(cwd=body.cwd, model=body.model)
    session = await ACP_WORKER.create_or_load_session(session_id=body.session_id, model=body.model)
    return {"initialize": initialized, "session": session, "status": acp_status()}


@router.post("/acp/answer")
async def acp_answer(body: AcpAnswerIn):
    return handle_blocking_request(body.method, body.params, isolated=body.isolated, autonomy=body.autonomy)
