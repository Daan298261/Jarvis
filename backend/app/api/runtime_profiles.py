from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..inference.model_stack import (
    list_specialist_models,
    normalize_role,
    routing_preferences_for_role,
)
from ..config import load_settings
from ..inference.hotswap import activate_runtime_profile
from ..inference.manager import MANAGER
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
from ..inference.security_gates import (
    authorized_runtime_profiles,
    gate_is_enabled,
    get_gate_status,
    list_gate_statuses,
    lock_gate,
    normalize_gate_role,
    set_gate_password,
    unlock_gate,
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
    enabled: bool = True


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
    enabled: bool | None = None


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


class RoleRouteRequest(BaseModel):
    role: str
    policy: str = "local-first"
    privacy_floor: str = "public-remote"
    max_cost_usd: float | None = None
    warm_models: list[str] = Field(default_factory=list)
    node_id: str = "localhost"
    load_factor: float = 0.0
    authorization_case: str | None = None
    human_confirmed: bool = False


class GatePasswordRequest(BaseModel):
    new_password: str
    current_password: str | None = None
    enable: bool | None = None


class GateUnlockRequest(BaseModel):
    password: str


def _node_from_request(
    *,
    node_id: str,
    warm_models: list[str],
    load_factor: float,
) -> RuntimeNodeState:
    return RuntimeNodeState(
        node_id=node_id,
        hostname=node_id,
        is_local=node_id in {"localhost", "local"},
        warm_models=tuple(warm_models),
        load_factor=load_factor,
    )


def _managed_security_role(profile_name: str, capability_tags: list[str] | tuple[str, ...]) -> str | None:
    tags = {str(tag).strip().lower() for tag in capability_tags}
    if profile_name == "deephat-7b" or "red-team" in tags:
        return "red-team"
    if profile_name in {"redsage-8b", "imperum-cyber"} or tags.intersection(
        {"blue-team", "dfir", "soc"}
    ):
        return "blue-team"
    return None


def _reject_generic_security_enable(
    *,
    profile_name: str,
    capability_tags: list[str] | tuple[str, ...],
    enabled: bool | None,
) -> None:
    if enabled is not True:
        return
    role = _managed_security_role(profile_name, capability_tags)
    if role is None:
        return
    raise HTTPException(
        status_code=403,
        detail={
            "reason": f"{role} profiles are enabled through the password-gated security-role API",
            "code": "security_gate_managed",
        },
    )


@router.get("")
async def list_profiles():
    return {
        "profiles": [profile.as_dict() for profile in list_runtime_profiles()],
        "policies": list(ROUTING_POLICIES),
        "security_gates": [status.as_dict() for status in list_gate_statuses()],
    }


@router.get("/specialists")
async def list_specialists(role: str | None = None):
    return {
        "models": [entry.as_dict() for entry in list_specialist_models(role=role)],
        "security_gates": [status.as_dict() for status in list_gate_statuses()],
    }


@router.get("/security-gates")
async def list_security_gates():
    return {"gates": [status.as_dict() for status in list_gate_statuses()]}


@router.get("/security-gates/{role}")
async def get_security_gate(role: str):
    try:
        return get_gate_status(role).as_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/security-gates/{role}/password")
async def configure_security_gate_password(role: str, body: GatePasswordRequest):
    try:
        status = set_gate_password(
            role,
            new_password=body.new_password,
            current_password=body.current_password,
            enable=body.enable,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    return status.as_dict()


@router.post("/security-gates/{role}/unlock")
async def unlock_security_gate(role: str, body: GateUnlockRequest):
    try:
        return unlock_gate(role, body.password).as_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/security-gates/{role}/lock")
async def lock_security_gate(role: str):
    try:
        return lock_gate(role).as_dict()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("")
async def create_profile(body: RuntimeProfileIn):
    _reject_generic_security_enable(
        profile_name=(body.name or "").strip().lower().replace(" ", "-"),
        capability_tags=body.capability_tags,
        enabled=body.enabled,
    )
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
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return profile.as_dict()


@router.post("/reset")
async def reset_profiles():
    profiles = reset_runtime_profiles()
    return {
        "profiles": [profile.as_dict() for profile in profiles],
        "security_gates": [status.as_dict() for status in list_gate_statuses()],
    }


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
    node = _node_from_request(
        node_id=body.node_id,
        warm_models=body.warm_models,
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
    node = _node_from_request(
        node_id=body.node_id,
        warm_models=body.warm_models,
        load_factor=body.load_factor,
    )
    return route_runtime(prefs, nodes=[node]).as_dict()


@router.post("/route-role/preview")
async def preview_role_route(body: RoleRouteRequest):
    """Resolve a Jarvis model role through the RFC-0048 specialist policy."""
    normalized = normalize_role(body.role)
    security_gate_role: str | None = None
    if normalized in {"blue-team", "dfir"}:
        security_gate_role = "blue-team"
    elif normalized == "red-team":
        security_gate_role = "red-team"

    if security_gate_role is not None and not gate_is_enabled(security_gate_role):
        raise HTTPException(
            status_code=403,
            detail={
                "reason": f"{security_gate_role} password gate is locked",
                "code": "password_gate_locked",
            },
        )

    if normalized == "red-team":
        if not body.human_confirmed or not (body.authorization_case or "").strip():
            raise HTTPException(
                status_code=403,
                detail={
                    "reason": "Red Team routing requires a case/authorization reference and explicit human confirmation in addition to the password gate",
                    "code": "red_authorization_required",
                },
            )

    try:
        prefs = routing_preferences_for_role(
            body.role,
            policy=body.policy,
            privacy_floor=body.privacy_floor,
            max_cost_usd=body.max_cost_usd,
            allow_manual_gate=normalized == "red-team",
        )
    except PermissionError as exc:
        raise HTTPException(
            status_code=403,
            detail={"reason": str(exc), "code": "manual_gate"},
        ) from exc
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail={"reason": str(exc), "code": "unknown_role"},
        ) from exc

    node = _node_from_request(
        node_id=body.node_id,
        warm_models=body.warm_models,
        load_factor=body.load_factor,
    )
    profiles = None
    if security_gate_role is not None:
        try:
            profiles = authorized_runtime_profiles(security_gate_role)
        except (KeyError, PermissionError) as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
    return route_runtime(prefs, nodes=[node], profiles=profiles).as_dict()


@router.get("/{profile_id}")
async def get_profile(profile_id: str):
    profile = get_runtime_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Runtime profile not found")
    return profile.as_dict()


@router.put("/{profile_id}")
async def update_profile(profile_id: str, body: RuntimeProfileUpdate):
    existing = get_runtime_profile(profile_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Runtime profile not found")
    capability_tags = body.capability_tags if body.capability_tags is not None else existing.capability_tags
    _reject_generic_security_enable(
        profile_name=existing.name,
        capability_tags=capability_tags,
        enabled=body.enabled,
    )
    try:
        profile = update_runtime_profile(profile_id, **body.model_dump(exclude_unset=True))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return profile.as_dict()


@router.post("/{profile_id}/activate")
async def activate_profile(profile_id: str):
    profile = get_runtime_profile(profile_id)
    if profile is None:
        raise HTTPException(status_code=404, detail="Runtime profile not found")
    try:
        await activate_runtime_profile(profile)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)[:500]) from exc
    settings = load_settings()
    return {
        "ok": True,
        "profile": profile.as_dict(),
        "load": await MANAGER.snapshot(settings),
    }


@router.delete("/{profile_id}")
async def remove_profile(profile_id: str):
    try:
        delete_runtime_profile(profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True}
