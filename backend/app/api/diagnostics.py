"""Desktop / System diagnostics API."""

from __future__ import annotations

import os

from fastapi import APIRouter

from ..diagnostics import build_diagnostics, diagnostics_text
from ..inference.manager import MANAGER
from ..config import load_settings

router = APIRouter(prefix="/api/diagnostics", tags=["diagnostics"])


@router.get("")
async def get_diagnostics():
    settings = load_settings()
    model = await MANAGER.snapshot(settings)
    payload = build_diagnostics(model_snapshot=model, backend_pid=os.getpid())
    return payload


@router.get("/text")
async def get_diagnostics_text():
    settings = load_settings()
    model = await MANAGER.snapshot(settings)
    payload = build_diagnostics(model_snapshot=model, backend_pid=os.getpid())
    return {"text": diagnostics_text(payload), "diagnostics": payload}
