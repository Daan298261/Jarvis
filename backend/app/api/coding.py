from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agent.acp import ACP_WORKER, acp_status, handle_blocking_request, list_acp_sessions
from ..agent.coding_workers import (
    approve_task_integration,
    cleanup_coding_task,
    complete_coding_task,
    integrate_coding_task,
    list_decision_inbox,
    request_task_integration,
    resolve_decision_inbox_item,
    start_coding_task,
)
from ..agent.escalation import get_escalation_package, list_escalation_packages
from ..agent.worktrees import WorktreeError, get_coding_task, list_coding_tasks
from ..coding.catalog import probe_cursor_models
from ..coding.routing import recommend_worker, recommendation_dict, workers_snapshot
from ..coding.usage import record_usage, usage_summary
from ..config import load_settings
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


class UsageIn(BaseModel):
    task_id: str = ""
    worker: str
    model: str
    task_class: str = "software engineering"
    complexity: int = 0
    input_tokens: int = 0
    cached_tokens: int = 0
    output_tokens: int = 0
    duration_seconds: float = 0
    verified_success: bool = False
    first_attempt_success: bool = False
    retries: int = 0
    estimated_cost_usd: float | None = None


class RouteIn(BaseModel):
    prompt: str
    task_class: str = "software engineering"


class StartCodingTaskIn(BaseModel):
    task_id: str
    repo: str | None = None


class CompleteCodingTaskIn(BaseModel):
    tests: dict[str, Any] = Field(default_factory=dict)


class ApproveIntegrationIn(BaseModel):
    approver: str = "human"


class ResolveDecisionIn(BaseModel):
    resolution: str = ""


def _coding_http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, WorktreeError):
        return HTTPException(400, str(exc))
    return HTTPException(500, str(exc))


@router.get("")
async def coding_overview():
    settings = load_settings()
    summary = await usage_summary()
    return {
        "workers": workers_snapshot(settings),
        "models": probe_cursor_models(settings),
        "usage": summary,
        "coding": settings.coding.model_dump(),
    }


@router.get("/models")
async def coding_models():
    return probe_cursor_models()


@router.get("/usage")
async def coding_usage():
    return await usage_summary()


@router.post("/usage")
async def add_coding_usage(body: UsageIn):
    row = await record_usage(**body.model_dump())
    return {
        "id": row.id,
        "estimated_cost_usd": row.estimated_cost_usd,
        "worker": row.worker,
        "model": row.model,
        "verified_success": row.verified_success,
    }


@router.post("/route")
async def coding_route(body: RouteIn):
    rec = await recommend_worker(body.prompt, body.task_class)
    return recommendation_dict(rec)


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


@router.get("/tasks")
async def coding_tasks(active_only: bool = False):
    return {"tasks": list_coding_tasks(active_only=active_only)}


@router.get("/tasks/{task_id}")
async def coding_task_detail(task_id: str):
    try:
        return get_coding_task(task_id).as_dict()
    except WorktreeError as exc:
        raise _coding_http_error(exc) from exc


@router.post("/tasks")
async def coding_task_start(body: StartCodingTaskIn):
    try:
        return start_coding_task(body.task_id, source=body.repo)
    except WorktreeError as exc:
        raise _coding_http_error(exc) from exc


@router.post("/tasks/{task_id}/complete")
async def coding_task_complete(task_id: str, body: CompleteCodingTaskIn | None = None):
    body = body or CompleteCodingTaskIn()
    try:
        return complete_coding_task(task_id, tests=body.tests)
    except WorktreeError as exc:
        raise _coding_http_error(exc) from exc


@router.post("/tasks/{task_id}/approve")
async def coding_task_approve(task_id: str, body: ApproveIntegrationIn | None = None):
    body = body or ApproveIntegrationIn()
    try:
        return approve_task_integration(task_id, approver=body.approver)
    except WorktreeError as exc:
        raise _coding_http_error(exc) from exc


@router.post("/tasks/{task_id}/integrate")
async def coding_task_integrate(task_id: str):
    try:
        return integrate_coding_task(task_id)
    except WorktreeError as exc:
        raise _coding_http_error(exc) from exc


@router.post("/tasks/{task_id}/cleanup")
async def coding_task_cleanup(task_id: str):
    try:
        return cleanup_coding_task(task_id)
    except WorktreeError as exc:
        raise _coding_http_error(exc) from exc


@router.get("/decision-inbox")
async def decision_inbox(open_only: bool = True):
    return {"items": list_decision_inbox(open_only=open_only)}


@router.post("/decision-inbox/{item_id}/resolve")
async def decision_inbox_resolve(item_id: str, body: ResolveDecisionIn | None = None):
    body = body or ResolveDecisionIn()
    try:
        return resolve_decision_inbox_item(item_id, resolution=body.resolution).as_dict()
    except WorktreeError as exc:
        raise _coding_http_error(exc) from exc
