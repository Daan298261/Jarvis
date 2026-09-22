from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import load_settings, save_settings
from ..mcp_server import jarvis_mcp_manifest
from ..tools.mcp_runtime import MCP

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class MCPServerIn(BaseModel):
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    env: dict[str, str] = {}
    enabled: bool = True


class MCPCallIn(BaseModel):
    mcp_tool: str
    arguments: dict[str, Any] = {}


def _decorate_server(server: dict[str, Any]) -> dict[str, Any]:
    name = str(server.get("name") or "")
    snap = MCP.snapshot().get(name) or {}
    item = dict(server)
    item["status"] = snap.get("status") or "not probed"
    item["tools"] = list(snap.get("tools") or [])
    item["error"] = snap.get("error") or ""
    item["agent_exposed"] = bool(item["tools"])
    return item


@router.get("/jarvis")
async def jarvis_mcp_server():
    return jarvis_mcp_manifest()


@router.get("")
async def list_mcp():
    settings = load_settings()
    return [_decorate_server(server) for server in settings.mcp_servers]


@router.post("")
async def add_mcp(body: MCPServerIn):
    settings = load_settings()
    item = body.model_dump()
    item["id"] = str(uuid.uuid4())
    settings.mcp_servers.append(item)
    save_settings(settings)
    status = await MCP.refresh(settings.mcp_servers)
    item["status"] = status.get(item["name"])
    return _decorate_server(item)


@router.delete("/{server_id}")
async def delete_mcp(server_id: str):
    settings = load_settings()
    before = len(settings.mcp_servers)
    settings.mcp_servers = [s for s in settings.mcp_servers if s.get("id") != server_id]
    if len(settings.mcp_servers) == before:
        raise HTTPException(404, "MCP server not found")
    save_settings(settings)
    await MCP.refresh(settings.mcp_servers)
    return {"ok": True}


@router.post("/refresh")
async def refresh_mcp():
    settings = load_settings()
    status = await MCP.refresh(settings.mcp_servers)
    return {
        "status": status,
        "servers": [_decorate_server(server) for server in settings.mcp_servers],
    }


@router.post("/call")
async def call_mcp(body: MCPCallIn):
    result = await MCP.call(body.mcp_tool, body.arguments or {})
    return {"ok": result.success, "output": result.output, "error": result.error}


@router.get("/usability")
async def mcp_usability():
    """Connections hub: MCP, vault, Supermemory, optional workers."""
    from ..memory.obsidian_vault import public_binding_status
    from ..modules import supermemory_runtime
    from ..swarm.workers import worker_catalog

    settings = load_settings()
    optional = []
    try:
        catalog = worker_catalog()
    except Exception:
        catalog = []
    for row in catalog:
        kind = str(row.get("kind") or "")
        worker_id = str(row.get("id") or "")
        if worker_id in {"supermemory", "browser-use", "ufo", "cua", "open-interpreter", "openhands"} or kind in {
            "memory",
            "browser",
            "computer",
            "code",
            "interpreter",
        }:
            optional.append(
                {
                    "id": worker_id,
                    "name": row.get("name") or worker_id,
                    "status": row.get("status") or "",
                    "available": str(row.get("status") or "").lower()
                    in {"ready", "healthy", "running", "available", "ok", "installed"},
                }
            )
    return {
        "mcp": [_decorate_server(server) for server in settings.mcp_servers],
        "vault": public_binding_status(),
        "supermemory": await supermemory_runtime.module_status(),
        "workers": optional,
        "agent_mcp_tools": MCP.connected_keys(),
    }
