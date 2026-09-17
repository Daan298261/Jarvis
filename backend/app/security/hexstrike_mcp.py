"""Register upstream HexStrike MCP into Jarvis owner-operator context (RFC-0106)."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from ..config import load_settings
from ..tools.mcp_runtime import MCP
from .hexstrike import audit_hexstrike

log = logging.getLogger(__name__)

HEXSTRIKE_MCP_SERVER_NAME = "hexstrike-upstream"
_MCP_STATUS: dict[str, str] = {}


def mcp_registration_status() -> dict[str, str]:
    return dict(_MCP_STATUS)


def _candidate_mcp_scripts(install: Path) -> list[Path]:
    names = (
        "hexstrike_mcp.py",
        "mcp_server.py",
        "hexstrike_mcp_server.py",
        "server/mcp_server.py",
    )
    return [install / name for name in names if (install / name).is_file()]


def build_hexstrike_mcp_server(
    *,
    install_path: Path,
    python_executable: str,
    host: str,
    port: int,
) -> list[dict[str, Any]]:
    """Build MCP server entries for the managed HexStrike install (loopback only)."""
    if host not in {"127.0.0.1", "::1", "localhost"}:
        return []
    loopback = "127.0.0.1" if host == "localhost" else host
    servers: list[dict[str, Any]] = [
        {
            "name": HEXSTRIKE_MCP_SERVER_NAME,
            "enabled": True,
            "transport": "streamable-http",
            "url": f"http://{loopback}:{port}/mcp",
        },
    ]
    for script in _candidate_mcp_scripts(install_path):
        servers.append(
            {
                "name": f"{HEXSTRIKE_MCP_SERVER_NAME}-stdio",
                "enabled": True,
                "transport": "stdio",
                "command": python_executable,
                "args": [str(script)],
                "env": {
                    "HEXSTRIKE_HOST": "127.0.0.1",
                    "HEXSTRIKE_PORT": str(port),
                },
            }
        )
        break
    return servers


async def register_hexstrike_mcp(
    *,
    install_path: Path,
    python_executable: str,
    host: str,
    port: int,
) -> dict[str, str]:
    """Refresh Jarvis MCP runtime with HexStrike upstream when the suite is active."""
    global _MCP_STATUS
    dynamic = build_hexstrike_mcp_server(
        install_path=install_path,
        python_executable=python_executable,
        host=host,
        port=port,
    )
    if not dynamic:
        audit_hexstrike("mcp_register_skipped", reason="non_loopback")
        return {"hexstrike": "skipped: non-loopback host"}

    settings = load_settings()
    base = [
        item
        for item in (settings.mcp_servers or [])
        if str(item.get("name") or "").strip() not in {HEXSTRIKE_MCP_SERVER_NAME, f"{HEXSTRIKE_MCP_SERVER_NAME}-stdio"}
    ]
    merged = base + dynamic
    try:
        status = await MCP.refresh(merged)
    except Exception as exc:
        last_error = str(exc)[:400]
        status = {HEXSTRIKE_MCP_SERVER_NAME: f"error: {last_error}"}
        log.debug("HexStrike MCP refresh failed", exc_info=True)
    _MCP_STATUS = status
    audit_hexstrike("mcp_registered", servers=list(status.keys()), detail=status)
    return status


async def unregister_hexstrike_mcp() -> None:
    global _MCP_STATUS
    settings = load_settings()
    base = [
        item
        for item in (settings.mcp_servers or [])
        if str(item.get("name") or "").strip() not in {HEXSTRIKE_MCP_SERVER_NAME, f"{HEXSTRIKE_MCP_SERVER_NAME}-stdio"}
    ]
    try:
        await MCP.refresh(base)
    except Exception:
        log.debug("HexStrike MCP unregister refresh failed", exc_info=True)
    _MCP_STATUS = {}
    audit_hexstrike("mcp_unregistered")
