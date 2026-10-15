from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from ..agent.acp import acp_status
from ..agent.coding_workers import coding_worker_catalog, route_software_task
from ..config import load_settings, save_settings
from ..mcp_server import jarvis_mcp_manifest
from ..tools.capabilities import capability_snapshot, optional_workers
from ..tools.exposure import exposure_catalog, tools_for_task
from ..tools.registry import REGISTRY
from ..workers.install import start_worker_install

router = APIRouter(prefix="/api/tools", tags=["tools"])


class RouteBody(BaseModel):
    prompt: str
    task_class: str | None = None
    files_hint: int = 0
    previous_failures: int = 0


@router.get("/chrome-connector")
async def chrome_connector_status():
    from ..tools.chrome_connector import execute_connector
    from ..tools.chrome_setup import setup_status
    status = await execute_connector("chrome_status")
    return {**setup_status(), **status.data}


@router.post("/chrome-connector/setup")
async def chrome_connector_setup(request: Request):
    from ..auth import is_local_owner_host
    if not request.client or not is_local_owner_host(request.client.host):
        raise HTTPException(403, "Prepare the Chrome connector from this computer's ANZU portal")
    import asyncio
    from ..tools.chrome_setup import prepare_connector
    try:
        return await asyncio.to_thread(prepare_connector)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/chrome-connector/package")
async def chrome_connector_package():
    import base64
    from ..tools.chrome_setup import connector_package
    return {"filename": "ANZU-Chrome-Connector.zip", "zip_base64": base64.b64encode(connector_package()).decode("ascii")}


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


@router.post("/optional-workers/{worker_id}/install")
async def install_optional_worker(worker_id: str):
    try:
        result = await start_worker_install(worker_id)
    except KeyError as exc:
        raise HTTPException(404, f"Unknown optional worker: {worker_id}") from exc
    return {
        "worker_id": worker_id,
        **result,
        "optional_workers": optional_workers(),
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
