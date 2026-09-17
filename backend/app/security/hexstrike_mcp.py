"""Register upstream HexStrike MCP into Jarvis owner-operator context (RFC-0106)."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..config import load_settings
from ..tools.mcp_runtime import MCP
from .hexstrike import audit_hexstrike

log = logging.getLogger(__name__)

HEXSTRIKE_MCP_SERVER_NAME = "hexstrike-upstream"
_MCP_STATUS: dict[str, str] = {}
_MCP_LAST_ERROR = ""


@dataclass
class McpRegistrationResult:
    ok: bool
    servers: dict[str, str] = field(default_factory=dict)
    error: str = ""
    transport: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "servers": dict(self.servers),
            "error": self.error,
            "transport": self.transport,
        }


def mcp_registration_status() -> dict[str, str]:
    return dict(_MCP_STATUS)


def mcp_registration_error() -> str:
    return _MCP_LAST_ERROR


def _loopback_server_url(host: str, port: int) -> str:
    cleaned = (host or "127.0.0.1").strip()
    if cleaned == "localhost":
        cleaned = "127.0.0.1"
    if cleaned not in {"127.0.0.1", "::1"}:
        raise ValueError("HexStrike MCP registration requires a loopback host")
    return f"http://{cleaned}:{int(port)}"


def build_hexstrike_mcp_server(
    *,
    install_path: Path,
    python_executable: str,
    host: str,
    port: int,
) -> list[dict[str, Any]]:
    """Build MCP server entries for the managed HexStrike install (loopback only)."""
    mcp_script = install_path / "hexstrike_mcp.py"
    if not mcp_script.is_file():
        return []
    server_url = _loopback_server_url(host, port)
    loopback = "127.0.0.1" if host in {"localhost", "127.0.0.1"} else host
    return [
        {
            "name": HEXSTRIKE_MCP_SERVER_NAME,
            "enabled": True,
            "transport": "stdio",
            "command": python_executable,
            "args": [str(mcp_script), "--server", server_url, "--stdio"],
            "env": {
                "HEXSTRIKE_HOST": "127.0.0.1",
                "HEXSTRIKE_PORT": str(port),
                "PYTHONUNBUFFERED": "1",
            },
        },
        {
            "name": f"{HEXSTRIKE_MCP_SERVER_NAME}-http",
            "enabled": True,
            "transport": "streamable-http",
            "url": f"http://{loopback}:{port}/mcp",
        },
    ]


def _tool_count_from_status(value: str) -> int | None:
    if value.endswith(" tools"):
        try:
            return int(value.split()[0])
        except ValueError:
            return None
    return None


def _status_ok(status: dict[str, str]) -> bool:
    if not status:
        return False
    for value in status.values():
        if value.startswith("error:") or value == "disabled":
            continue
        count = _tool_count_from_status(value)
        if count is not None:
            return count > 0
        if value and not value.startswith("error:"):
            return True
    return False


async def register_hexstrike_mcp(
    *,
    install_path: Path,
    python_executable: str,
    host: str,
    port: int,
) -> McpRegistrationResult:
    """Refresh Jarvis MCP runtime with HexStrike upstream when the suite is active."""
    global _MCP_STATUS, _MCP_LAST_ERROR
    dynamic = build_hexstrike_mcp_server(
        install_path=install_path,
        python_executable=python_executable,
        host=host,
        port=port,
    )
    if not dynamic:
        _MCP_LAST_ERROR = "Managed install is missing hexstrike_mcp.py"
        _MCP_STATUS = {HEXSTRIKE_MCP_SERVER_NAME: f"error: {_MCP_LAST_ERROR}"}
        audit_hexstrike("mcp_register_failed", reason=_MCP_LAST_ERROR)
        return McpRegistrationResult(False, servers=_MCP_STATUS, error=_MCP_LAST_ERROR)

    settings = load_settings()
    base = [
        item
        for item in (settings.mcp_servers or [])
        if not str(item.get("name") or "").strip().startswith(HEXSTRIKE_MCP_SERVER_NAME)
    ]

    last_error = ""
    chosen_transport = ""
    status: dict[str, str] = {}
    for server in dynamic:
        transport = str(server.get("transport") or "stdio")
        try:
            status = await MCP.refresh(base + [server])
        except Exception as exc:
            last_error = str(exc)[:400]
            status = {str(server.get("name")): f"error: {last_error}"}
            log.debug("HexStrike MCP refresh failed (%s)", transport, exc_info=True)
            continue
        if _status_ok(status):
            chosen_transport = transport
            break

    _MCP_STATUS = status
    if not _status_ok(status):
        _MCP_LAST_ERROR = last_error or "HexStrike MCP list_tools did not succeed on stdio or streamable-http"
        audit_hexstrike("mcp_register_failed", detail=status, error=_MCP_LAST_ERROR)
        return McpRegistrationResult(False, servers=status, error=_MCP_LAST_ERROR)

    _MCP_LAST_ERROR = ""
    audit_hexstrike("mcp_registered", transport=chosen_transport, detail=status)
    return McpRegistrationResult(True, servers=status, transport=chosen_transport)


async def unregister_hexstrike_mcp() -> None:
    global _MCP_STATUS, _MCP_LAST_ERROR
    settings = load_settings()
    base = [
        item
        for item in (settings.mcp_servers or [])
        if not str(item.get("name") or "").strip().startswith(HEXSTRIKE_MCP_SERVER_NAME)
    ]
    try:
        await MCP.refresh(base)
    except Exception:
        log.debug("HexStrike MCP unregister refresh failed", exc_info=True)
    _MCP_STATUS = {}
    _MCP_LAST_ERROR = ""
    audit_hexstrike("mcp_unregistered")
