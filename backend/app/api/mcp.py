from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import load_settings, save_settings
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


@router.get("")
async def list_mcp():
    settings = load_settings()
    return settings.mcp_servers


@router.post("")
async def add_mcp(body: MCPServerIn):
    settings = load_settings()
    item = body.model_dump()
    item["id"] = str(uuid.uuid4())
    settings.mcp_servers.append(item)
    save_settings(settings)
    status = await MCP.refresh(settings.mcp_servers)
    item["status"] = status.get(item["name"])
    return item


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
    return status
