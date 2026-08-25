from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..config import load_settings, save_settings
from ..tools.mcp_presets import (
    instantiate_preset,
    list_presets,
    missing_env,
    public_server,
    sanitize_env,
    sanitize_env_from,
)
from ..tools.mcp_runtime import MCP

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class MCPServerIn(BaseModel):
    name: str
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = []
    url: str | None = None
    env: dict[str, str] = {}
    env_from: list[str] = Field(default_factory=list)
    enabled: bool = True


def _prepare(body: MCPServerIn) -> dict[str, Any]:
    try:
        env = sanitize_env(body.env)
        env_from = sanitize_env_from(body.env_from)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return {
        "name": body.name,
        "transport": body.transport,
        "command": body.command,
        "args": list(body.args or []),
        "url": body.url or "",
        "env": env,
        "env_from": env_from,
        "enabled": body.enabled,
    }


@router.get("/presets")
async def mcp_presets():
    return list_presets()


@router.post("/presets/{preset_id}")
async def add_preset(preset_id: str):
    settings = load_settings()
    try:
        item = instantiate_preset(preset_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    existing = {str(row.get("preset") or row.get("name") or "") for row in settings.mcp_servers}
    if item["preset"] in existing or item["name"] in existing:
        raise HTTPException(409, f"MCP preset {item['name']} is already configured")
    item["id"] = str(uuid.uuid4())
    settings.mcp_servers.append(item)
    save_settings(settings)
    status = await MCP.refresh(settings.mcp_servers)
    return public_server(item, status.get(item["name"]))


@router.get("")
async def list_mcp():
    settings = load_settings()
    out = []
    for server in settings.mcp_servers:
        if not server.get("enabled", True):
            status = "disabled"
        else:
            missing = missing_env(server)
            if missing:
                status = f"missing env: {', '.join(missing)}"
            else:
                count = MCP.tool_count(str(server.get("name") or ""))
                status = f"{count} tools" if count else "configured"
        out.append(public_server(server, status))
    return out


@router.post("")
async def add_mcp(body: MCPServerIn):
    settings = load_settings()
    item = _prepare(body)
    item["id"] = str(uuid.uuid4())
    settings.mcp_servers.append(item)
    save_settings(settings)
    status = await MCP.refresh(settings.mcp_servers)
    return public_server(item, status.get(item["name"]))


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
    return await MCP.refresh(settings.mcp_servers)
