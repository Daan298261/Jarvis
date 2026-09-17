"""Owner approval queue for parked API actions (RFC-0110 backend)."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..policy.approval_pending import (
    DECISION_MODES,
    decide_pending,
    get_pending,
    list_pending_approvals,
    pending_response,
)
from ..security.hexstrike_pending import execute_parked_hexstrike_action

router = APIRouter(prefix="/api/approvals", tags=["approvals"])


class ApprovalDecideBody(BaseModel):
    mode: str = Field(..., min_length=3, max_length=16)
    owner_note: str | None = Field(default=None, max_length=500)


@router.get("/pending")
async def approvals_pending():
    return {"pending": list_pending_approvals()}


@router.get("/pending/{pending_id}")
async def approval_detail(pending_id: str):
    try:
        row = get_pending(pending_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown or resolved pending approval") from None
    return pending_response(row)


@router.post("/pending/{pending_id}/decide")
async def approval_decide(pending_id: str, body: ApprovalDecideBody):
    mode = body.mode.strip().lower()
    if mode not in DECISION_MODES:
        raise HTTPException(status_code=400, detail=f"mode must be one of: {', '.join(sorted(DECISION_MODES))}")
    try:
        outcome = decide_pending(pending_id, mode, owner_note=body.owner_note)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown or resolved pending approval") from None
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    if outcome.get("status") == "denied":
        return outcome

    action_kind = str(outcome.get("action_kind") or "")
    if action_kind.startswith("hexstrike."):
        try:
            ctx = dict(outcome.get("context") or {})
            ctx["_permission_ids"] = outcome.get("permission_ids") or ctx.get("_permission_ids") or []
            result = await execute_parked_hexstrike_action(
                action_kind,
                ctx,
                decision=str(outcome.get("decision") or ""),
            )
        except (ValueError, PermissionError, RuntimeError, KeyError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        outcome["executed"] = True
        outcome["result"] = result
    return outcome
