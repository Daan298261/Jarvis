from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agent.loop import AGENT
from ..agent.workflows import (
    GUIDE_SECTIONS,
    compose_prompt,
    delete_workflow,
    get_workflow,
    list_workflows,
    merge_parameter_values,
    save_workflow,
    workflow_from_dict,
)

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


class WorkflowIn(BaseModel):
    id: str | None = None
    name: str
    description: str = ""
    category: str = "custom"
    execution_mode: str = "balanced"
    parameters: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[dict[str, Any]] = Field(default_factory=list)


class WorkflowRun(BaseModel):
    id: str | None = None
    workflow: WorkflowIn | None = None
    parameters: dict[str, str] = Field(default_factory=dict)
    execution_mode: str | None = None
    autonomy: str | None = None
    profile: str | None = None


def _task_dict(task) -> dict[str, Any]:
    from ..api.tasks import _task_dict as as_task

    return as_task(task)


@router.get("/guide")
async def guide():
    return {"sections": GUIDE_SECTIONS}


@router.get("")
async def list_all():
    return [item.to_dict() for item in list_workflows()]


@router.get("/{workflow_id}")
async def get_one(workflow_id: str):
    workflow = get_workflow(workflow_id)
    if not workflow:
        raise HTTPException(404, "Workflow not found")
    return workflow.to_dict()


@router.post("")
async def create_or_update(body: WorkflowIn):
    try:
        saved = save_workflow(body.model_dump())
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return saved.to_dict()


@router.delete("/{workflow_id}")
async def remove(workflow_id: str):
    try:
        deleted = delete_workflow(workflow_id)
    except PermissionError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not deleted:
        raise HTTPException(404, "Workflow not found")
    return {"ok": True}


@router.post("/run")
async def run_workflow(body: WorkflowRun):
    if body.workflow is not None:
        workflow = workflow_from_dict(body.workflow.model_dump(), builtin=False)
    elif body.id:
        workflow = get_workflow(body.id)
        if not workflow:
            raise HTTPException(404, "Workflow not found")
    else:
        raise HTTPException(400, "Provide a workflow id or a workflow body")
    if not workflow.steps:
        raise HTTPException(400, "A workflow needs at least one step")
    values = merge_parameter_values(workflow, body.parameters)
    prompt = compose_prompt(workflow, values)
    mode = body.execution_mode or workflow.execution_mode or "balanced"
    task = await AGENT.create_task(prompt, body.autonomy, body.profile, mode)
    return {"task": _task_dict(task), "prompt": prompt, "workflow_id": workflow.id}
