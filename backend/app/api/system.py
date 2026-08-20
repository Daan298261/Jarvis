from __future__ import annotations

from fastapi import APIRouter

from ..hardware import hardware_dict
from ..inference.manager import MANAGER
from ..config import load_settings

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
        "allowed_directories": settings.allowed_directories,
    }
