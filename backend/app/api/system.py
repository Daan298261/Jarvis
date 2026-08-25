from __future__ import annotations

from fastapi import APIRouter

from ..agent.autonomy import catalog as autonomy_catalog, resolve_autonomy
from ..agent.execution import available_modes
from ..agent.routing import list_classes, list_workers
from ..config import load_settings
from ..hardware import hardware_dict, hardware_view
from ..inference.manager import MANAGER
from ..security import token_is_too_short, usable_auth_token, uvicorn_bind_host
from ..phone import phone_status
from ..voice import voice_status

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("")
async def system_info():
    settings = load_settings()
    hardware = hardware_dict()
    view = hardware_view()
    model = await MANAGER.snapshot(settings)
    autonomy = resolve_autonomy(settings.autonomy)
    return {
        "hardware": hardware,
        "hardware_view": view,
        "model": model,
        "bind_host": uvicorn_bind_host(settings.lan_access),
        "bind_port": settings.bind_port,
        "lan_access": settings.lan_access,
        "auth_token_configured": bool(usable_auth_token()),
        "auth_token_too_short": token_is_too_short(),
        "auth_required": bool(settings.lan_access and usable_auth_token()),
        "autonomy": autonomy.name,
        "autonomy_mode": {
            "name": autonomy.name,
            "label": autonomy.label,
            "description": autonomy.description,
            "confirms": autonomy.confirms,
        },
        "autonomy_modes": autonomy_catalog(),
        "execution_mode": settings.execution_mode,
        "execution_modes": [
            {"name": mode.name, "label": mode.label, "description": mode.description}
            for mode in available_modes()
        ],
        "allowed_directories": settings.allowed_directories,
        "workers": list_workers(),
        "task_classes": list_classes(),
        "voice": voice_status(),
        "phone": phone_status(),
    }
