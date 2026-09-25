from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..recovery.admission import WriteAdmissionError, admission_status
from ..recovery.checkpoint import (
    create_checkpoint,
    get_checkpoint,
    list_checkpoints,
    operator_summary,
    verify_and_promote_checkpoint,
)
from ..recovery.journal import list_journal_entries, verify_journal_chain
from ..recovery.prune import prune_journal
from ..recovery.rollback import (
    apply_rollback,
    build_rollback_plan,
    get_rollback_status,
    resume_or_apply_rollback,
    start_rollback_run,
)
from ..recovery.types import CheckpointTag

router = APIRouter(prefix="/api/recovery", tags=["recovery"])


class CheckpointCreateIn(BaseModel):
    notes: str = ""
    actor: str = "operator"


class CheckpointVerifyIn(BaseModel):
    actor: str = "operator"


class RollbackPlanIn(BaseModel):
    checkpoint_id: str
    forward_replay: bool = False


class RollbackApplyIn(BaseModel):
    checkpoint_id: str
    forward_replay: bool = False
    actor: str = "operator"


class RollbackResumeIn(BaseModel):
    run_id: str


class PruneIn(BaseModel):
    retain_through_seq: int | None = None
    actor: str = "operator"


@router.get("/status")
async def recovery_status():
    summary = operator_summary()
    summary["admission"] = admission_status()
    summary["journal_chain_ok"], summary["journal_chain_detail"] = verify_journal_chain()
    run = get_rollback_status()
    summary["active_rollback"] = run
    return summary


@router.get("/checkpoints")
async def checkpoints_list():
    return {"checkpoints": list_checkpoints()}


@router.post("/checkpoints")
async def checkpoints_create(body: CheckpointCreateIn):
    cp = create_checkpoint(tag=CheckpointTag.CANDIDATE, notes=body.notes, actor=body.actor)
    return cp


@router.get("/checkpoints/{checkpoint_id}")
async def checkpoints_get(checkpoint_id: str):
    cp = get_checkpoint(checkpoint_id)
    if not cp:
        raise HTTPException(404, "checkpoint not found")
    return cp


@router.post("/checkpoints/{checkpoint_id}/verify")
async def checkpoints_verify(checkpoint_id: str, body: CheckpointVerifyIn | None = None):
    body = body or CheckpointVerifyIn()
    try:
        return verify_and_promote_checkpoint(checkpoint_id, actor=body.actor)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/journal")
async def journal_list(after_seq: int = 0, limit: int = 100):
    return {"entries": list_journal_entries(after_seq=after_seq, limit=limit)}


@router.post("/rollback/plan")
async def rollback_plan(body: RollbackPlanIn):
    try:
        return build_rollback_plan(body.checkpoint_id, forward_replay=body.forward_replay)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/rollback/apply")
async def rollback_apply(body: RollbackApplyIn):
    try:
        return apply_rollback(
            body.checkpoint_id,
            forward_replay=body.forward_replay,
            actor=body.actor,
        )
    except WriteAdmissionError as exc:
        raise HTTPException(409, str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/rollback/start")
async def rollback_start(body: RollbackApplyIn):
    try:
        return start_rollback_run(
            body.checkpoint_id,
            forward_replay=body.forward_replay,
            actor=body.actor,
        )
    except (KeyError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/rollback/resume")
async def rollback_resume(body: RollbackResumeIn):
    try:
        return resume_or_apply_rollback(body.run_id)
    except KeyError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.get("/rollback/status")
async def rollback_status(run_id: str | None = None):
    run = get_rollback_status(run_id)
    if not run:
        raise HTTPException(404, "rollback run not found")
    return run


@router.post("/journal/prune")
async def journal_prune(body: PruneIn | None = None):
    body = body or PruneIn()
    try:
        return prune_journal(actor=body.actor, retain_through_seq=body.retain_through_seq)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
