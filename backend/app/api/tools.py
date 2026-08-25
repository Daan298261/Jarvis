from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..agent.routing import NATIVE_WORKER, OPTIONAL_WORKERS, list_classes, list_workers
from ..agent.skills import list_skills
from ..agent.trajectories import list_trajectories
from ..config import load_settings, save_settings
from ..tools.registry import REGISTRY

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools():
    settings = load_settings()
    REGISTRY.apply_settings(settings)
    return REGISTRY.list_tools()


@router.get("/catalog")
async def tools_catalog():
    settings = load_settings()
    REGISTRY.apply_settings(settings)
    return {
        "tools": REGISTRY.list_tools(),
        "workers": list_workers(),
        "classes": list_classes(),
        "trajectories": list_trajectories(limit=20),
        "skills": list_skills(),
    }


def _set_worker_enabled(worker_name: str, enabled: bool) -> dict:
    name = (worker_name or "").strip().lower()
    if name == NATIVE_WORKER:
        raise HTTPException(400, "The native worker cannot be disabled")
    if name not in OPTIONAL_WORKERS:
        raise HTTPException(404, "Unknown worker")
    settings = load_settings()
    disabled = [item for item in (settings.disabled_workers or []) if item != name]
    if not enabled:
        disabled.append(name)
    settings.disabled_workers = disabled
    save_settings(settings)
    REGISTRY.apply_settings(settings)
    row = next((worker for worker in list_workers() if worker["name"] == name), None)
    return row or {"name": name, "enabled": enabled, "available": False}


@router.post("/workers/{worker_name}/enable")
async def enable_worker(worker_name: str):
    return _set_worker_enabled(worker_name, True)


@router.post("/workers/{worker_name}/disable")
async def disable_worker(worker_name: str):
    return _set_worker_enabled(worker_name, False)


@router.post("/{tool_name}/enable")
async def enable_tool(tool_name: str):
    settings = load_settings()
    settings.disabled_tools = [name for name in settings.disabled_tools if name != tool_name]
    save_settings(settings)
    REGISTRY.apply_settings(settings)
    if tool_name not in REGISTRY.tools:
        raise HTTPException(404, "Unknown tool")
    return {"name": tool_name, "enabled": True}


@router.post("/{tool_name}/disable")
async def disable_tool(tool_name: str):
    settings = load_settings()
    if tool_name not in settings.disabled_tools:
        settings.disabled_tools.append(tool_name)
    save_settings(settings)
    REGISTRY.apply_settings(settings)
    if tool_name not in REGISTRY.tools:
        raise HTTPException(404, "Unknown tool")
    return {"name": tool_name, "enabled": False}
