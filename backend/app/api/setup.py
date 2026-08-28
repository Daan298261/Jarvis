"""First-run setup API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import load_settings, save_settings
from ..hardware import hardware_dict
from ..runtime_install import (
    COMPONENT_IDS,
    component_status_payload,
    discover_component_states,
    start_component_install,
    start_selected_installs,
)
from ..setup_recommend import recommend_from_hardware
from ..setup_state import (
    WIZARD_STEPS,
    complete_setup,
    load_setup_state,
    mark_step_complete,
    needs_setup,
    save_setup_state,
    wizard_preset_to_budget,
)
from ..swarm.budgets import set_node_budget
from ..swarm.nodes import load_or_create_local_node_id
from ..swarm.roles import set_node_role_policy

router = APIRouter(prefix="/api/setup", tags=["setup"])


class SetupPatch(BaseModel):
    current_step: str | None = None
    completed_steps: list[str] | None = None
    jarvis_role: str | None = None
    recommended_class: str | None = None
    role_policies: dict[str, str] | None = None
    resource_preset: str | None = None
    global_percent: int | None = None
    resource_mode: str | None = None
    resource_limits: dict[str, Any] | None = None
    inference_choice: str | None = None
    inference_profile: str | None = None
    remote_host: str | None = None
    remote_port: int | None = None
    install_expert_27b: bool | None = None
    install_playwright: bool | None = None
    desktop_prefs: dict[str, Any] | None = None
    last_error: str | None = None
    completed: bool | None = None


class AdvanceBody(BaseModel):
    step: str
    next_step: str | None = None
    patch: dict[str, Any] = Field(default_factory=dict)


class InstallBody(BaseModel):
    component: str | None = None
    all_selected: bool = False


@router.get("/status")
async def setup_status():
    state = load_setup_state()
    return {
        "needs_setup": needs_setup(),
        "state": state,
        "steps": list(WIZARD_STEPS),
        "components": component_status_payload(),
    }


@router.get("/recommend")
async def setup_recommend():
    return recommend_from_hardware()


@router.get("/hardware")
async def setup_hardware():
    return {"hardware": hardware_dict(), "recommendation": recommend_from_hardware()}


@router.put("/state")
async def put_setup_state(body: SetupPatch):
    patch = {k: v for k, v in body.model_dump().items() if v is not None}
    if "current_step" in patch and patch["current_step"] not in WIZARD_STEPS:
        raise HTTPException(400, f"Invalid step: {patch['current_step']}")
    state = save_setup_state(patch)
    return {"state": state}


@router.post("/advance")
async def advance_setup(body: AdvanceBody):
    if body.step not in WIZARD_STEPS:
        raise HTTPException(400, f"Invalid step: {body.step}")
    if body.patch:
        save_setup_state(body.patch)
    state = mark_step_complete(body.step, next_step=body.next_step)
    return {"state": state}


@router.post("/apply")
async def apply_setup():
    """Apply setup_state to settings, budget, and role policies for the localhost node."""
    state = load_setup_state()
    node_id = load_or_create_local_node_id()
    settings = load_settings()

    choice = str(state.get("inference_choice") or "local")
    if choice == "remote":
        settings.inference.backend = "remote"
        settings.inference.host = str(state.get("remote_host") or "127.0.0.1")
        settings.inference.port = int(state.get("remote_port") or 8088)
        settings.inference.auto_load = False
    elif choice == "later":
        settings.inference.auto_load = False
    else:
        settings.inference.backend = "llama.cpp"
        settings.inference.profile = str(state.get("inference_profile") or "balanced")
        settings.inference.auto_load = True
    save_settings(settings)

    try:
        budget = wizard_preset_to_budget(str(state.get("resource_preset") or "dynamic"))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if state.get("resource_preset") == "custom":
        if state.get("global_percent") is not None:
            budget["global_percent"] = int(state["global_percent"])
        if state.get("resource_mode"):
            budget["mode"] = str(state["resource_mode"])
        if state.get("resource_limits"):
            budget["limits"] = state["resource_limits"]
    elif state.get("global_percent") is not None and str(state.get("resource_preset")) == "custom":
        budget["global_percent"] = int(state["global_percent"])
    # Allow slider override for dynamic/balanced when user moved global percent.
    if state.get("global_percent") is not None and str(state.get("resource_preset")) in {
        "dynamic",
        "balanced",
        "minimal",
        "maximum",
        "custom",
    }:
        if str(state.get("resource_preset")) == "custom" or state.get("resource_mode") == "dynamic":
            budget["global_percent"] = int(state["global_percent"])
            if str(state.get("resource_preset")) != "custom":
                # Keep named preset but honor percent for dynamic slider.
                if str(state.get("resource_preset")) == "dynamic":
                    budget["global_percent"] = int(state["global_percent"])

    try:
        await set_node_budget(
            node_id,
            {
                "preset": budget["preset"],
                "mode": budget["mode"],
                "global_percent": budget["global_percent"],
                "limits": budget.get("limits") or state.get("resource_limits") or {},
            },
        )
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    policies = state.get("role_policies") or {}
    for role, policy in policies.items():
        try:
            await set_node_role_policy(node_id, str(role), str(policy))
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, f"Invalid role policy {role}={policy}: {exc}") from exc

    return {
        "ok": True,
        "node_id": node_id,
        "budget": budget,
        "role_policies": policies,
        "inference": {
            "choice": choice,
            "backend": settings.inference.backend,
            "profile": settings.inference.profile,
            "host": settings.inference.host,
            "port": settings.inference.port,
        },
        "desktop_prefs": state.get("desktop_prefs") or {},
    }


@router.post("/complete")
async def finish_setup(body: dict[str, Any] | None = None):
    body = body or {}
    if body.get("apply", True):
        await apply_setup()
    state = complete_setup()
    if body.get("without_local_model"):
        state = save_setup_state({"last_error": "", "inference_choice": state.get("inference_choice") or "later"})
        state = complete_setup()
    return {"ok": True, "state": state}


@router.post("/reset")
async def reset_setup():
    state = save_setup_state(
        {
            "completed": False,
            "current_step": "welcome",
            "completed_steps": [],
            "last_error": "",
            "component_status": {},
        },
        replace=False,
    )
    return {"state": state}


@router.get("/components")
async def list_components():
    discover_component_states()
    return {"components": component_status_payload(), "ids": list(COMPONENT_IDS)}


@router.post("/install")
async def install_components(body: InstallBody):
    if body.all_selected:
        results = await start_selected_installs()
        return {"components": results, "status": component_status_payload()}
    if not body.component:
        raise HTTPException(400, "component required unless all_selected")
    if body.component not in COMPONENT_IDS:
        raise HTTPException(400, f"Unknown component: {body.component}")
    result = await start_component_install(body.component)
    return {"component": result, "status": component_status_payload()}
