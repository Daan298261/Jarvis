from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from ..config import load_settings, save_settings
from ..tools.registry import REGISTRY

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsUpdate(BaseModel):
    autonomy: str | None = None
    allowed_directories: list[str] | None = None
    default_timeout_seconds: int | None = None
    retry_limit: int | None = None
    logging_level: str | None = None
    lan_access: bool | None = None
    bind_host: str | None = None
    bind_port: int | None = None
    backup_enabled: bool | None = None
    profile: str | None = None
    execution_mode: str | None = None
    browser_headless: bool | None = None


@router.get("")
async def get_settings():
    return load_settings().model_dump()


@router.put("")
async def update_settings(body: SettingsUpdate):
    settings = load_settings()
    if body.autonomy is not None:
        settings.autonomy = body.autonomy
    if body.allowed_directories is not None:
        settings.allowed_directories = body.allowed_directories
    if body.default_timeout_seconds is not None:
        settings.default_timeout_seconds = body.default_timeout_seconds
    if body.retry_limit is not None:
        settings.retry_limit = body.retry_limit
    if body.logging_level is not None:
        settings.logging_level = body.logging_level
    if body.lan_access is not None:
        settings.lan_access = body.lan_access
        settings.bind_host = "0.0.0.0" if body.lan_access else "127.0.0.1"
        settings.auth_required = bool(body.lan_access)
    if body.bind_host is not None:
        settings.bind_host = body.bind_host
    if body.bind_port is not None:
        settings.bind_port = body.bind_port
    if body.backup_enabled is not None:
        settings.backup_enabled = body.backup_enabled
    if body.profile is not None:
        settings.inference.profile = body.profile
    if body.execution_mode is not None:
        settings.execution_mode = body.execution_mode
    if body.browser_headless is not None:
        settings.browser.headless = body.browser_headless
    save_settings(settings)
    REGISTRY.apply_settings(settings)
    return settings.model_dump()
