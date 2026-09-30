"""RFC-0031 ApprovalGrant + undo API (Decision Inbox / owner channels)."""

from __future__ import annotations

import json
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..policy.approval_grant import (
    TRUSTED_CHANNELS,
    decide_approval_request,
    get_pending_grant,
    list_grant_audit,
    list_pending_grants,
    reject_timeout_pending,
)
from ..policy.reversibility import resolve_action_effect
from ..policy.undo_journal import (
    apply_undo,
    describe_undo,
    list_undo_audit,
    list_undo_records,
)

router = APIRouter(prefix="/api/reversibility", tags=["reversibility"])


class DecideBody(BaseModel):
    decision: Literal["allow_once", "always", "deny", "approve", "reject"]
    origin_channel: str = Field(..., min_length=2, max_length=32)
    actor: str = Field(..., min_length=1, max_length=128)
    session_id: str | None = Field(default=None, max_length=128)
    owner_note: str | None = Field(default=None, max_length=500)


class EffectProbeBody(BaseModel):
    tool_name: str
    action: str | None = None
    arguments: dict[str, Any] | None = None


@router.get("/pending")
async def pending_approvals(task_id: str | None = None, open_only: bool = True):
    return {"pending": list_pending_grants(task_id=task_id, open_only=open_only)}


@router.get("/pending/{pending_id}")
async def pending_detail(pending_id: str):
    try:
        return get_pending_grant(pending_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown pending approval") from None


async def _resume_task_with_grant(task_id: str, grant: dict[str, Any]) -> dict[str, Any]:
    """Attach grant_id to the parked confirmation payload and resume the same step."""
    from ..agent.loop import AGENT
    from ..db.models import Task
    from ..db.session import SessionLocal

    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            return {"resumed": False, "error": "task not found"}
        try:
            payload = json.loads(task.confirmation_payload or "{}")
        except json.JSONDecodeError:
            payload = {}
        payload["grant_id"] = grant.get("id")
        payload["action_id"] = grant.get("action_id")
        payload["pending_approval_id"] = grant.get("pending_id")
        if not payload.get("name"):
            payload["name"] = grant.get("tool_name")
        if "arguments" not in payload:
            payload["arguments"] = {}
        task.confirmation_payload = json.dumps(payload)
        await session.commit()
    await AGENT.confirm_task(task_id, True, grant_mode="allow_once")
    return {"resumed": True}


@router.post("/pending/{pending_id}/decide")
async def pending_decide(pending_id: str, body: DecideBody):
    channel = body.origin_channel.strip().lower()
    if channel not in TRUSTED_CHANNELS:
        raise HTTPException(
            status_code=403,
            detail="origin_channel cannot create an ApprovalGrant",
        )
    try:
        outcome = decide_approval_request(
            pending_id,
            decision=body.decision,
            origin_channel=channel,
            actor=body.actor,
            session_id=body.session_id,
            owner_note=body.owner_note,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown pending approval") from None
    except TimeoutError as exc:
        raise HTTPException(status_code=408, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    task_id = outcome.get("task_id")
    if outcome.get("status") == "approved" and task_id and outcome.get("grant"):
        try:
            resume = await _resume_task_with_grant(str(task_id), outcome["grant"])
            outcome.update(resume)
        except Exception as exc:  # noqa: BLE001
            outcome["resumed"] = False
            outcome["resume_error"] = str(exc)[:300]
    elif outcome.get("status") == "rejected" and task_id:
        try:
            from ..agent.loop import AGENT

            await AGENT.confirm_task(str(task_id), False)
            outcome["terminated"] = True
        except Exception as exc:  # noqa: BLE001
            outcome["terminated"] = False
            outcome["terminate_error"] = str(exc)[:300]
    return outcome


@router.post("/pending/{pending_id}/timeout")
async def pending_timeout(pending_id: str):
    try:
        row = reject_timeout_pending(pending_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown pending approval") from None
    if row.get("task_id"):
        try:
            from ..agent.loop import AGENT

            await AGENT.confirm_task(str(row["task_id"]), False)
        except Exception:
            pass
    return {"status": "timeout", "pending": row}


@router.get("/undo")
async def undo_list(task_id: str | None = None, run_id: str | None = None, ready_only: bool = False):
    return {"records": list_undo_records(task_id=task_id, run_id=run_id, ready_only=ready_only)}


@router.get("/undo/{record_id}")
async def undo_preview(record_id: str):
    try:
        return describe_undo(record_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown undo record") from None


@router.post("/undo/{record_id}/apply")
async def undo_apply(record_id: str):
    try:
        outcome = apply_undo(record_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown undo record") from None
    if outcome.get("status") == "not_implemented":
        raise HTTPException(
            status_code=422,
            detail={
                "status": "not_implemented",
                "reason": outcome.get("reason"),
                "record_id": record_id,
            },
        )
    if outcome.get("status") == "conflict":
        raise HTTPException(
            status_code=409,
            detail={
                "status": "conflict",
                "reason": outcome.get("reason"),
                "record_id": record_id,
            },
        )
    return outcome


@router.get("/audit")
async def reversibility_audit(limit: int = 100):
    return {
        "grants": list_grant_audit(limit=limit),
        "undo": list_undo_audit(limit=limit),
    }


@router.post("/effect")
async def probe_effect(body: EffectProbeBody):
    meta = resolve_action_effect(
        body.tool_name,
        action=body.action,
        arguments=body.arguments,
    )
    return meta.as_dict()
