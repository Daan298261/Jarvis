"""REST API for Skill Forge (RFC-0173). Portal UX wires later — backend only."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..skills.approval import ApprovalError
from ..skills.forge import ForgeError, forge
from ..skills.marketplace import MarketplaceError
from ..skills.permissions import PrivilegeExpansionError
from ..skills.routing import goal_runtime_skill_context, search_skills
from ..skills.store import get_candidate, get_version, list_candidates, list_skills
from ..trajectories.schema import JarvisTrajectoryV1
from ..trajectories.store import get_trajectory

router = APIRouter(prefix="/api/skill-forge", tags=["skill-forge"])


class ObserveIn(BaseModel):
    trajectory_id: str | None = None
    trajectory: dict[str, Any] | None = None
    auto_extract: bool = False


class PipelineIn(BaseModel):
    trajectory_id: str | None = None
    trajectory: dict[str, Any] | None = None
    profile_id: str | None = None
    actor: str | None = None


class CandidateActionIn(BaseModel):
    actor: str = Field(min_length=1)
    admin: bool = True
    reason: str = ""
    profile_id: str | None = None
    task_capabilities: list[str] = Field(default_factory=list)
    node_capabilities: list[str] = Field(default_factory=list)
    parent_capabilities: list[str] = Field(default_factory=list)


class RepairIn(BaseModel):
    trajectory_id: str | None = None
    trajectory: dict[str, Any] | None = None
    manifest_patch: dict[str, Any] | None = None
    created_by: str = "skill_forge_repair"


class ImportIn(BaseModel):
    manifest: dict[str, Any]
    imported_from: str | None = "marketplace"


class SearchIn(BaseModel):
    query: str
    persona_id: str | None = None
    goal_id: str | None = None
    task_class: str | None = None
    limit: int = 5


class RollbackIn(BaseModel):
    actor: str = Field(min_length=1)
    to_version_id: str | None = None


class DisableIn(BaseModel):
    actor: str = Field(min_length=1)


def _http(exc: Exception) -> HTTPException:
    if isinstance(exc, (ForgeError, ApprovalError, MarketplaceError, PrivilegeExpansionError, ValueError)):
        return HTTPException(status_code=400, detail=str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    if isinstance(exc, LookupError):
        return HTTPException(status_code=404, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _load_trajectory(body_trajectory_id: str | None, body_trajectory: dict[str, Any] | None) -> JarvisTrajectoryV1:
    if body_trajectory is not None:
        return JarvisTrajectoryV1.model_validate(body_trajectory)
    if not body_trajectory_id:
        raise ForgeError("trajectory_id or trajectory is required")
    loaded = get_trajectory(body_trajectory_id)
    if loaded is None:
        raise LookupError(f"trajectory not found: {body_trajectory_id}")
    return loaded


@router.get("")
async def skill_forge_index() -> dict[str, Any]:
    return {
        "skills": [item.model_dump(mode="json") for item in list_skills()],
        "candidates": [item.model_dump(mode="json") for item in list_candidates(limit=50)],
    }


@router.get("/skills")
async def get_skills() -> dict[str, Any]:
    return {"skills": [item.model_dump(mode="json") for item in list_skills()]}


@router.get("/candidates")
async def get_candidates(status: str | None = None, limit: int = 50) -> dict[str, Any]:
    return {
        "candidates": [
            item.model_dump(mode="json") for item in list_candidates(status=status, limit=limit)
        ]
    }


@router.get("/candidates/{candidate_id}")
async def get_one_candidate(candidate_id: str) -> dict[str, Any]:
    candidate = get_candidate(candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    return candidate.model_dump(mode="json")


@router.get("/versions/{version_id}")
async def get_one_version(version_id: str) -> dict[str, Any]:
    version = get_version(version_id)
    if version is None:
        raise HTTPException(status_code=404, detail="version not found")
    return version.model_dump(mode="json")


@router.post("/observe")
async def observe(body: ObserveIn) -> dict[str, Any]:
    try:
        trajectory = _load_trajectory(body.trajectory_id, body.trajectory)
        return forge.observe_trajectory(trajectory, auto_extract=body.auto_extract)
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/pipeline")
async def run_pipeline(body: PipelineIn) -> dict[str, Any]:
    try:
        trajectory = _load_trajectory(body.trajectory_id, body.trajectory)
        return forge.run_pipeline(trajectory, actor=body.actor, profile_id=body.profile_id)
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/sandbox")
async def sandbox_candidate(candidate_id: str, body: CandidateActionIn | None = None) -> dict[str, Any]:
    body = body or CandidateActionIn(actor="system")
    try:
        candidate = forge.sandbox(
            candidate_id,
            profile_id=body.profile_id,
            task_capabilities=body.task_capabilities or None,
            node_capabilities=body.node_capabilities or None,
            parent_capabilities=body.parent_capabilities or None,
        )
        return candidate.model_dump(mode="json")
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/verify")
async def verify_candidate(candidate_id: str) -> dict[str, Any]:
    try:
        return forge.verify(candidate_id).model_dump(mode="json")
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/request-approval")
async def request_approval(candidate_id: str, body: CandidateActionIn | None = None) -> dict[str, Any]:
    body = body or CandidateActionIn(actor="skill_forge")
    try:
        return forge.request_owner_approval(candidate_id, actor=body.actor).model_dump(mode="json")
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/approve")
async def approve(candidate_id: str, body: CandidateActionIn) -> dict[str, Any]:
    try:
        return forge.approve(candidate_id, actor=body.actor, admin=body.admin).model_dump(mode="json")
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/reject")
async def reject(candidate_id: str, body: CandidateActionIn) -> dict[str, Any]:
    try:
        return forge.reject(candidate_id, actor=body.actor, reason=body.reason or "rejected").model_dump(
            mode="json"
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/activate")
async def activate(candidate_id: str, body: CandidateActionIn) -> dict[str, Any]:
    try:
        return forge.activate(
            candidate_id,
            actor=body.actor,
            profile_id=body.profile_id,
            task_capabilities=body.task_capabilities or None,
            node_capabilities=body.node_capabilities or None,
            parent_capabilities=body.parent_capabilities or None,
        ).model_dump(mode="json")
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/candidates/{candidate_id}/permissions")
async def permissions_preview(candidate_id: str, body: CandidateActionIn | None = None) -> dict[str, Any]:
    body = body or CandidateActionIn(actor="system")
    try:
        return forge.permission_preview(
            candidate_id,
            profile_id=body.profile_id,
            task_capabilities=body.task_capabilities or None,
            node_capabilities=body.node_capabilities or None,
            parent_capabilities=body.parent_capabilities or None,
        )
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/skills/{skill_id}/repair")
async def repair_skill(skill_id: str, body: RepairIn | None = None) -> dict[str, Any]:
    body = body or RepairIn()
    try:
        trajectory = None
        if body.trajectory is not None or body.trajectory_id:
            trajectory = _load_trajectory(body.trajectory_id, body.trajectory)
        candidate = forge.repair(
            skill_id,
            trajectory=trajectory,
            manifest_patch=body.manifest_patch,
            created_by=body.created_by,
        )
        return candidate.model_dump(mode="json")
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/skills/{skill_id}/rollback")
async def rollback_skill(skill_id: str, body: RollbackIn) -> dict[str, Any]:
    try:
        version = forge.rollback(skill_id, actor=body.actor, to_version_id=body.to_version_id)
        return version.model_dump(mode="json")
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/skills/{skill_id}/disable")
async def disable_skill(skill_id: str, body: DisableIn) -> dict[str, Any]:
    try:
        version = forge.disable(skill_id, actor=body.actor)
        return {"ok": True, "disabled_version": version.model_dump(mode="json") if version else None}
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/import")
async def import_marketplace(body: ImportIn) -> dict[str, Any]:
    try:
        candidate = forge.import_marketplace(body.manifest, imported_from=body.imported_from)
        return candidate.model_dump(mode="json")
    except Exception as exc:
        raise _http(exc) from exc


@router.post("/search")
async def search(body: SearchIn) -> dict[str, Any]:
    return {
        "results": search_skills(
            body.query,
            persona_id=body.persona_id,
            goal_id=body.goal_id,
            task_class=body.task_class,
            limit=body.limit,
        )
    }


@router.get("/goals/{goal_id}/skills")
async def goal_skills(goal_id: str, objective: str = "", task_class: str = "") -> dict[str, Any]:
    return goal_runtime_skill_context(goal_id, objective or goal_id, task_class=task_class)
