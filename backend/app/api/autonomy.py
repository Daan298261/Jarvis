from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..agent.persistence import (
    PERSISTENCE_MODES,
    create_autonomy_profile,
    get_autonomy_profile,
    list_autonomy_profiles,
    scheduler_eligible_agents,
    scheduler_tick,
    update_autonomy_profile,
)
from ..agent.proactivity import (
    PROACTIVITY_MODES,
    approve_proactive_action,
    authorize_execute_within_policy,
    can_enqueue_executable_work,
    create_proactive_action,
    effective_behavior,
    effective_proactivity,
    get_away_mode,
    list_proactive_actions,
    set_away_mode,
)

router = APIRouter(prefix="/api/autonomy", tags=["autonomy"])


class AutonomyProfileIn(BaseModel):
    name: str
    persistence: str = "ONE_SHOT"
    proactivity: str = "DISABLED"
    agent_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AutonomyProfileUpdate(BaseModel):
    name: str | None = None
    persistence: str | None = None
    proactivity: str | None = None
    agent_id: str | None = None
    metadata: dict[str, Any] | None = None


class AwayModeUpdate(BaseModel):
    enabled: bool | None = None
    pause_proactivity: bool | None = None
    message: str | None = None


class ProactiveActionIn(BaseModel):
    parent_agent_id: str
    trigger: str
    evidence: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    budget: dict[str, Any] = Field(default_factory=dict)
    configured_proactivity: str
    persistence: str = "ONE_SHOT"
    capability: str = ""
    node_id: str = "localhost"


class ExecuteAuthorizeIn(BaseModel):
    node_id: str = "localhost"
    capability: str
    budget: dict[str, Any] = Field(default_factory=dict)


class SchedulerTickIn(BaseModel):
    task_status_by_agent: dict[str, str] = Field(default_factory=dict)


@router.get("/modes")
async def list_modes():
    return {
        "persistence_modes": list(PERSISTENCE_MODES),
        "proactivity_modes": list(PROACTIVITY_MODES),
    }


@router.get("/profiles")
async def list_profiles():
    return {"profiles": [profile.as_dict() for profile in list_autonomy_profiles()]}


@router.post("/profiles")
async def create_profile(body: AutonomyProfileIn):
    try:
        profile = create_autonomy_profile(
            name=body.name,
            persistence=body.persistence,
            proactivity=body.proactivity,
            agent_id=body.agent_id,
            metadata=body.metadata,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    behavior = effective_behavior(persistence=profile.persistence, proactivity=profile.proactivity)
    payload = profile.as_dict()
    payload["effective"] = behavior
    return payload


@router.get("/profiles/{profile_id}")
async def get_profile(profile_id: str):
    profile = get_autonomy_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    payload = profile.as_dict()
    payload["effective"] = effective_behavior(
        persistence=profile.persistence,
        proactivity=profile.proactivity,
    )
    return payload


@router.put("/profiles/{profile_id}")
async def update_profile(profile_id: str, body: AutonomyProfileUpdate):
    try:
        profile = update_autonomy_profile(
            profile_id,
            name=body.name,
            persistence=body.persistence,
            proactivity=body.proactivity,
            agent_id=body.agent_id,
            metadata=body.metadata,
        )
    except ValueError as exc:
        status = 404 if "not found" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    payload = profile.as_dict()
    payload["effective"] = effective_behavior(
        persistence=profile.persistence,
        proactivity=profile.proactivity,
    )
    return payload


@router.get("/away-mode")
async def read_away_mode():
    away = get_away_mode()
    return away.as_dict()


@router.put("/away-mode")
async def update_away_mode(body: AwayModeUpdate):
    away = set_away_mode(
        enabled=body.enabled,
        pause_proactivity=body.pause_proactivity,
        message=body.message,
    )
    return away.as_dict()


@router.get("/profiles/{profile_id}/effective")
async def profile_effective_behavior(profile_id: str):
    profile = get_autonomy_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Profile not found")
    return effective_behavior(persistence=profile.persistence, proactivity=profile.proactivity)


@router.get("/scheduler")
async def scheduler_state(task_status_by_agent: str | None = None):
    statuses: dict[str, str] = {}
    if task_status_by_agent:
        for part in task_status_by_agent.split(","):
            if ":" not in part:
                continue
            agent_id, status = part.split(":", 1)
            statuses[agent_id.strip()] = status.strip()
    return {"eligible": scheduler_eligible_agents(task_status_by_agent=statuses or None)}


@router.post("/scheduler/tick")
async def run_scheduler_tick(body: SchedulerTickIn):
    return scheduler_tick(task_status_by_agent=body.task_status_by_agent or None)


@router.get("/proactive")
async def list_proactive(parent_agent_id: str | None = None):
    return {
        "actions": [
            action.as_dict()
            for action in list_proactive_actions(parent_agent_id=parent_agent_id)
        ]
    }


@router.post("/proactive")
async def record_proactive_action(body: ProactiveActionIn):
    try:
        action = create_proactive_action(
            parent_agent_id=body.parent_agent_id,
            trigger=body.trigger,
            evidence=body.evidence,
            rationale=body.rationale,
            budget=body.budget,
            configured_proactivity=body.configured_proactivity,
            persistence=body.persistence,
            capability=body.capability,
            node_id=body.node_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return action.as_dict()


@router.post("/proactive/{action_id}/approve")
async def approve_proactive(action_id: str):
    try:
        action = approve_proactive_action(action_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return action.as_dict()


@router.post("/proactive/authorize-execute")
async def authorize_execute(body: ExecuteAuthorizeIn):
    return await authorize_execute_within_policy(
        node_id=body.node_id,
        capability=body.capability,
        budget=body.budget,
    )


@router.get("/matrix/effective-proactivity")
async def matrix_effective_proactivity():
    away = get_away_mode()
    rows = []
    for proactivity in PROACTIVITY_MODES:
        rows.append(
            {
                "configured": proactivity,
                "effective": effective_proactivity(proactivity, away_mode=away),
                "away_mode_active": away.enabled and away.pause_proactivity,
            }
        )
    return {"rows": rows}


@router.get("/enqueue-check")
async def enqueue_check(proactivity: str, approved: bool = False):
    return {
        "proactivity": proactivity,
        "approved": approved,
        "can_enqueue": can_enqueue_executable_work(proactivity, approved=approved),
    }
