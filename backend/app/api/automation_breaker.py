from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..auth import require_owner_private_key
from ..automation.audit import list_breaker_audit
from ..automation.breaker import (
    AutomationBreakerError,
    ensure_automation,
    get_automation_breaker,
    list_automation_breakers,
    reenable_automation,
    set_failure_threshold,
)
from ..automation.ids import automation_actor_id

router = APIRouter(prefix="/api/automation-breaker", tags=["automation-breaker"])
Owner = Depends(require_owner_private_key)


class ThresholdIn(BaseModel):
    failure_threshold: int = Field(ge=1, le=100)


class ReenableIn(BaseModel):
    actor: str = "owner"


def _public_view(record) -> dict[str, Any]:
    payload = record.as_dict()
    payload["recent_failed_runs"] = [
        {"task_or_run_id": item} for item in (record.recent_failed_run_ids or [])
    ]
    return payload


@router.get("")
async def list_breakers():
    return {"automations": [_public_view(item) for item in list_automation_breakers()]}


@router.get("/audit")
async def breaker_audit(automation_id: str | None = None, limit: int = 100):
    return {"events": list_breaker_audit(automation_id=automation_id, limit=limit)}


@router.get("/{automation_id}")
async def get_breaker(automation_id: str):
    record = get_automation_breaker(automation_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Automation breaker record not found")
    return _public_view(record)


@router.put("/{automation_id}/threshold", dependencies=[Owner])
async def update_threshold(automation_id: str, body: ThresholdIn):
    ensure_automation(automation_id)
    record = set_failure_threshold(automation_id, body.failure_threshold, actor="owner")
    return _public_view(record)


@router.post("/{automation_id}/reenable", dependencies=[Owner])
async def reenable(automation_id: str, body: ReenableIn | None = None):
    body = body or ReenableIn()
    actor = (body.actor or "owner").strip()
    if actor == automation_actor_id(automation_id):
        raise HTTPException(status_code=403, detail="Automation cannot re-enable itself")
    try:
        record = reenable_automation(automation_id, actor=actor)
    except AutomationBreakerError as exc:
        status = 403 if "cannot re-enable itself" in str(exc) else 400
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return _public_view(record)
