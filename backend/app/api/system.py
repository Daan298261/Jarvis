from __future__ import annotations

from fastapi import APIRouter

from ..agent.acp import acp_status
from ..config import load_settings
from ..hardware import detect_hardware, hardware_dict
from ..inference.benchmarks import list_benchmarks
from ..inference.hardware_gate import hardware_purchase_gate
from ..inference.manager import MANAGER
from ..mcp_server import jarvis_mcp_manifest
from ..tools.capabilities import capability_snapshot

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("")
async def system_info():
    settings = load_settings()
    hardware = hardware_dict()
    model = await MANAGER.snapshot(settings)
    return {
        "hardware": hardware,
        "model": model,
        "bind_host": settings.bind_host,
        "bind_port": settings.bind_port,
        "lan_access": settings.lan_access,
        "autonomy": settings.autonomy,
        "execution_mode": settings.execution_mode,
        "allowed_directories": settings.allowed_directories,
        "capabilities": capability_snapshot(),
        "jarvis_mcp": jarvis_mcp_manifest(),
        "cursor_acp": acp_status(),
    }
