from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agent.portability import (
    PortabilityError,
    SchedulerError,
    acquire_runtime_lease,
    create_agent_profile,
    get_agent_profile,
    list_agent_profiles,
    list_audit_events,
    migrate_agent,
    release_runtime_lease,
    resume_agent,
    suspend_agent,
    update_agent_state,
)

router = APIRouter(prefix="/api/agent-portability", tags=["agent-portability"])


class CreateAgentIn(BaseModel):
    name: str
    memory: dict[str, Any] = Field(default_factory=dict)
    policy: dict[str, Any] = Field(default_factory=dict)
    skill_refs: list[str] = Field(default_factory=list)
    goals: list[dict[str, Any]] = Field(default_factory=list)
    task_state: dict[str, Any] = Field(default_factory=dict)
    provenance: list[dict[str, Any]] = Field(default_factory=list)
    required_tools: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)


class UpdateStateIn(BaseModel):
    memory: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    skill_refs: list[str] | None = None
    goals: list[dict[str, Any]] | None = None
    task_state: dict[str, Any] | None = None
    provenance: list[dict[str, Any]] | None = None
    required_tools: list[str] | None = None
    required_capabilities: list[str] | None = None


class LeaseIn(BaseModel):
    runtime_profile_id: str
    node_id: str = "localhost"


class MigrateIn(BaseModel):
    target_runtime_profile_id: str
    node_id: str = "localhost"


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, SchedulerError):
        return HTTPException(status_code=409, detail={"code": exc.code, "message": str(exc)})
    if isinstance(exc, PortabilityError):
        status = 404 if exc.code.endswith("not_found") else 400
        if exc.code == "lease_active":
            status = 409
        return HTTPException(status_code=status, detail={"code": exc.code, "message": str(exc)})
    return HTTPException(status_code=400, detail=str(exc))


@router.get("")
async def list_agents(limit: int = 100):
    return {"agents": await list_agent_profiles(limit=limit)}


@router.post("")
async def create_agent(body: CreateAgentIn):
    try:
        return await create_agent_profile(
            name=body.name,
            memory=body.memory,
            policy=body.policy,
            skill_refs=body.skill_refs,
            goals=body.goals,
            task_state=body.task_state,
            provenance=body.provenance,
            required_tools=body.required_tools,
            required_capabilities=body.required_capabilities,
        )
    except PortabilityError as exc:
        raise _http_error(exc) from exc


@router.get("/audit")
async def agent_audit(agent_id: str | None = None, limit: int = 100):
    return {"events": await list_audit_events(agent_id=agent_id, limit=limit)}


@router.get("/{agent_id}")
async def get_agent(agent_id: str):
    try:
        return await get_agent_profile(agent_id)
    except PortabilityError as exc:
        raise _http_error(exc) from exc


@router.put("/{agent_id}/state")
async def patch_agent_state(agent_id: str, body: UpdateStateIn):
    try:
        return await update_agent_state(
            agent_id,
            memory=body.memory,
            policy=body.policy,
            skill_refs=body.skill_refs,
            goals=body.goals,
            task_state=body.task_state,
            provenance=body.provenance,
            required_tools=body.required_tools,
            required_capabilities=body.required_capabilities,
        )
    except PortabilityError as exc:
        raise _http_error(exc) from exc


@router.post("/{agent_id}/lease")
async def lease_agent(agent_id: str, body: LeaseIn):
    try:
        return await acquire_runtime_lease(
            agent_id,
            runtime_profile_id=body.runtime_profile_id,
            node_id=body.node_id,
        )
    except (PortabilityError, SchedulerError) as exc:
        raise _http_error(exc) from exc


@router.post("/{agent_id}/migrate")
async def migrate_agent_runtime(agent_id: str, body: MigrateIn):
    try:
        return await migrate_agent(
            agent_id,
            target_runtime_profile_id=body.target_runtime_profile_id,
            node_id=body.node_id,
        )
    except (PortabilityError, SchedulerError) as exc:
        raise _http_error(exc) from exc


@router.post("/{agent_id}/suspend")
async def suspend_agent_runtime(agent_id: str):
    try:
        return await suspend_agent(agent_id)
    except PortabilityError as exc:
        raise _http_error(exc) from exc


@router.post("/{agent_id}/resume")
async def resume_agent_runtime(agent_id: str, body: LeaseIn):
    try:
        return await resume_agent(
            agent_id,
            runtime_profile_id=body.runtime_profile_id,
            node_id=body.node_id,
        )
    except (PortabilityError, SchedulerError) as exc:
        raise _http_error(exc) from exc


@router.delete("/leases/{lease_id}")
async def release_lease(lease_id: str):
    try:
        return await release_runtime_lease(lease_id)
    except PortabilityError as exc:
        raise _http_error(exc) from exc
