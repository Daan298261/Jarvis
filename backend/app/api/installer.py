"""Installer owner actions (RFC-0124 clean reinstall)."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..installer.clean_reinstall import start_clean_reinstall_detached
from ..installer.owned_paths import owned_paths_preview

router = APIRouter(prefix="/api/installer", tags=["installer"])


class CleanReinstallStartBody(BaseModel):
    confirm: bool = Field(..., description="Owner must pass true after reading owned roots.")
    setup_exe: str | None = None


@router.get("/clean-reinstall/preview")
async def clean_reinstall_preview():
    return owned_paths_preview()


@router.post("/clean-reinstall/start")
async def clean_reinstall_start(body: CleanReinstallStartBody):
    if not body.confirm:
        raise HTTPException(status_code=400, detail="confirm must be true")
    result = start_clean_reinstall_detached(setup_exe=body.setup_exe)
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail=str(result.get("error") or "start failed"))
    return result
