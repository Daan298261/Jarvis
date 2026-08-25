from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent.acp import acp_status
from ..agent.coding_workers import coding_worker_catalog, route_software_task
from ..config import load_settings, save_settings
from ..mcp_server import jarvis_mcp_manifest
from ..tools.capabilities import capability_snapshot
from ..tools.exposure import exposure_catalog, tools_for_task
from ..tools.registry import REGISTRY

router = APIRouter(prefix="/api/tools", tags=["tools"])


class RouteBody(BaseModel):
    prompt: str
    task_class: str | None = None
    files_hint: int = 0
    previous_failures: int = 0


@router.get("")
async def list_tools():
    settings = load_settings()
    REGISTRY.apply_settings(settings)
    return REGISTRY.list_tools()


@router.get("/catalog")
async def tool_catalog():
    settings = load_settings()
    REGISTRY.apply_settings(settings)
    caps = capability_snapshot()
    return {
        "tools": REGISTRY.list_tools(),
        **caps,
        "jarvis_mcp": jarvis_mcp_manifest(),
        "cursor_acp": acp_status(),
    }


@router.get("/coding-workers")
async def coding_workers(prompt: str | None = None, task_class: str | None = None):
    body: dict[str, Any] = {"workers": coding_worker_catalog()}
    if prompt:
        body["route"] = route_software_task(prompt, task_class=task_class or "").as_dict()
    return body


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
