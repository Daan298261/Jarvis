from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..inference.runtime_profiles import (
    create_runtime_profile,
    delete_runtime_profile,
    get_runtime_profile,
    list_runtime_profiles,
    reset_runtime_profiles,
    update_runtime_profile,
)
from ..inference.runtime_router import (
    ROUTING_POLICIES,
    AgentRoutingPreferences,
    RuntimeNodeState,
    route_runtime,
)

router = APIRouter(prefix="/api/runtime-profiles", tags=["runtime-profiles"])


class RuntimeProfileIn(BaseModel):
    name: str
    label: str | None = None
    model: str
    provider: str = "openai-compat"
    endpoint: str
    context_limit: int = 16384
    quantization: str = ""
    privacy_class: str = "trusted-remote"
    cost_ceiling_usd: float | None = None
    capability_tags: list[str] = Field(default_factory=list)
    model_profile: str | None = None
    specialization_tags: list[str] = Field(default_factory=list)
    is_local: bool = False
    description: str = ""


class RuntimeProfileUpdate(BaseModel):
    label: str | None = None
    model: str | None = None
    provider: str | None = None
    endpoint: str | None = None
    context_limit: int | None = None
    quantization: str | None = None
    privacy_class: str | None = None
    cost_ceiling_usd: float | None = None
    capability_tags: list[str] | None = None
    model_profile: str | None = None
    specialization_tags: list[str] | None = None
    is_local: bool | None = None
    description: str | None = None


class RouteRequest(BaseModel):
    preferred_profiles: list[str] = Field(default_factory=list)
    forbidden_profiles: list[str] = Field(default_factory=list)
    force_profile: str | None = None
    policy: str = "local-first"
    required_capabilities: list[str] = Field(default_factory=list)
    task_specialization: str | None = None
    privacy_floor: str = "public-remote"
    max_cost_usd: float | None = None
    warm_models: list[str] = Field(default_factory=list)
    node_id: str = "localhost"
    load_factor: float = 0.0


@router.get("")
async def list_profiles():
    return {
        "profiles": [profile.as_dict() for profile in list_runtime_profiles()],
        "policies": list(ROUTING_POLICIES),
    }


@router.post("")
async def create_profile(body: RuntimeProfileIn):
    try:
        profile = create_runtime_profile(
            name=body.name,
            label=body.label,
            model=body.model,
            provider=body.provider,
            endpoint=body.endpoint,
            context_limit=body.context_limit,
            quantization=body.quantization,
            privacy_class=body.privacy_class,
            cost_ceiling_usd=body.cost_ceiling_usd,
            capability_tags=body.capability_tags,
            model_profile=body.model_profile,
            specialization_tags=body.specialization_tags,
            is_local=body.is_local,
            description=body.description,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return profile.as_dict()


@router.post("/reset")
async def reset_profiles():
    profiles = reset_runtime_profiles()
    return {"profiles": [profile.as_dict() for profile in profiles]}


@router.post("/route")
async def select_runtime(body: RouteRequest):
    prefs = AgentRoutingPreferences(
        preferred_profiles=tuple(body.preferred_profiles),
        forbidden_profiles=tuple(body.forbidden_profiles),
        force_profile=body.force_profile,
        policy=body.policy,
        required_capabilities=tuple(body.required_capabilities),
        task_specialization=body.task_specialization,
        privacy_floor=body.privacy_floor,
        max_cost_usd=body.max_cost_usd,
    )
    node = RuntimeNodeState(
        node_id=body.node_id,
        hostname=body.node_id,
        is_local=body.node_id in {"localhost", "local"},
        warm_models=tuple(body.warm_models),
        load_factor=body.load_factor,
    )
    decision = route_runtime(prefs, nodes=[node])
    if not decision.accepted:
        raise HTTPException(
            status_code=409,
            detail={
                "reason": decision.reason,
                "code": decision.code,
            },
        )
    return decision.as_dict()


@router.post("/route/preview")
async def preview_route(body: RouteRequest):
    """Non-failing route preview that always returns the decision payload."""
    prefs = AgentRoutingPreferences(
        preferred_profiles=tuple(body.preferred_profiles),
        forbidden_profiles=tuple(body.forbidden_profiles),
        force_profile=body.force_profile,
        policy=body.policy,
        required_capabilities=tuple(body.required_capabilities),
        task_specialization=body.task_specialization,
        privacy_floor=body.privacy_floor,
        max_cost_usd=body.max_cost_usd,
    )
    node = RuntimeNodeState(
        node_id=body.node_id,
        hostname=body.node_id,
        is_local=body.node_id in {"localhost", "local"},
        warm_models=tuple(body.warm_models),
        load_factor=body.load_factor,
    )
    return route_runtime(prefs, nodes=[node]).as_dict()


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    profile = get_runtime_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Runtime profile not found")
    return profile.as_dict()


@router.put("/{profile_id}")
async def update_profile(profile_id: str, body: RuntimeProfileUpdate):
    try:
        profile = update_runtime_profile(profile_id, **body.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return profile.as_dict()


@router.delete("/{profile_id}")
async def remove_profile(profile_id: str):
    try:
        delete_runtime_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
