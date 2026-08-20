from __future__ import annotations

from fastapi import APIRouter, HTTPException

from ..config import load_settings, save_settings
from ..tools.registry import REGISTRY

router = APIRouter(prefix="/api/tools", tags=["tools"])


@router.get("")
async def list_tools():
    settings = load_settings()
    REGISTRY.apply_settings(settings)
    return REGISTRY.list_tools()


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
