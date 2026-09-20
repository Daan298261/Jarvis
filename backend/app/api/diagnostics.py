"""Desktop / System diagnostics API."""

from __future__ import annotations

import os

from fastapi import APIRouter

from ..diagnostics import build_diagnostics, diagnostics_text
from ..inference.manager import MANAGER
from ..config import load_settings
from ..observability.rolling_log import RETENTION, list_events, log_path

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


@router.get("/rolling-log")
async def get_rolling_log(limit: int = 200, kind: str | None = None):
    """Last 24h of redacted backend events (exceptions, tool calls, HTTP 5xx)."""
    capped = max(1, min(limit, 1000))
    events = list_events(limit=capped, kind=kind or None)
    return {
        "path": str(log_path()),
        "retention_hours": int(RETENTION.total_seconds() // 3600),
        "count": len(events),
        "events": events,
    }
