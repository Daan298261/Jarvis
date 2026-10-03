from __future__ import annotations

from fastapi import APIRouter

from ..agent.acp import acp_status
from ..config import live_allowed_directories, load_settings
from ..hardware import detect_hardware, hardware_dict
from ..inference.benchmarks import list_benchmarks
from ..inference.hardware_gate import hardware_purchase_gate
from ..inference.manager import MANAGER
from ..mcp_server import jarvis_mcp_manifest
from ..swarm.snapshot import swarm_snapshot
from ..tools.capabilities import capability_snapshot

from ..systems.self_check import run_self_check
from ..runtime.elevation import prompt_windows_uac, snapshot as elevation_snapshot

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/self-check")
async def system_self_check():
    """Launch readiness snapshot for the initializing overlay (RFC-0082)."""
    return await run_self_check()


@router.get("/elevation")
async def system_elevation():
    return elevation_snapshot()


@router.post("/elevation/prompt")
async def system_elevation_prompt():
    """Show the Windows administrator prompt. The owner only clicks Yes or No."""
    return prompt_windows_uac()


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
        "allowed_directories": live_allowed_directories(settings.allowed_directories),
        "capabilities": capability_snapshot(),
        "jarvis_mcp": jarvis_mcp_manifest(),
        "cursor_acp": acp_status(),
        "swarm": await swarm_snapshot(),
    }
