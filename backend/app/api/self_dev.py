from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..agent.self_dev import (
    KillSwitchActive,
    activate_kill_switch,
    build_report,
    checkpoint_commit,
    clear_kill_switch,
    experimental_launch_plan,
    note_activity,
    refuse_trusted_merge,
    run_verification_gate,
    snapshot,
    start_trial,
)
from ..agent.worktrees import WorktreeError, discard_worktree, get_worktree, worktree_status
from ..agent.development_queue import OWNER, StaleQueue
from ..agent.development_scheduler import DEVELOPMENT, DevelopmentConfig

router = APIRouter(prefix="/api/self-dev", tags=["self-dev"])


class RfcSelection(BaseModel):
    revision: str
    queued: bool = True


class DriveRfcImport(BaseModel):
    file_id: str
    title: str
    content: str


class MissionDecision(BaseModel):
    task_id: str
    expected_payload: str
    approved: bool


class QueueReorder(BaseModel):
    order: list[str]
    expected_revision: int
    reason: str = ""


class QueueMove(BaseModel):
    item_id: str
    expected_revision: int
    to: int | None = None
    delta: int = 0


class QueueRelease(BaseModel):
    item_id: str
    expected_revision: int


class QueueUndo(BaseModel):
    history_id: str
    expected_revision: int


class AwayToggle(BaseModel):
    enabled: bool


def _queue_error(exc: ValueError) -> HTTPException:
    return HTTPException(409, str(exc))


async def _owner_tasks() -> list[dict]:
    """Foreground owner work persisted by the agent, shown beside development work."""
    from sqlalchemy import select

    from ..db.models import Task
    from ..db.session import SessionLocal

    async with SessionLocal() as session:
        rows = (await session.execute(
            select(Task).where(Task.status.in_(["queued", "running", "waiting"])).order_by(Task.created_at)
        )).scalars().all()
    return [{"id": row.id, "title": row.title, "status": row.status, "stage": row.stage, "kind": "owner_task"} for row in rows]


@router.get("/scheduler")
async def scheduler_status():
    return DEVELOPMENT.public()


@router.get("/scheduler/queue")
async def scheduler_queue():
    view = DEVELOPMENT.queue_view(DEVELOPMENT.state())
    return {**view, "owner_tasks": await _owner_tasks(), "status": DEVELOPMENT.phase(DEVELOPMENT.state())}


@router.post("/scheduler/queue/reorder")
async def scheduler_queue_reorder(body: QueueReorder):
    try:
        return await DEVELOPMENT.reorder(body.order, expected_revision=body.expected_revision, actor=OWNER, reason=body.reason or "Reordered by owner")
    except (StaleQueue, ValueError) as exc:
        raise _queue_error(exc) from exc


@router.post("/scheduler/queue/move")
async def scheduler_queue_move(body: QueueMove):
    try:
        return await DEVELOPMENT.move(body.item_id, expected_revision=body.expected_revision, actor=OWNER, reason="Moved by owner", to=body.to, delta=body.delta)
    except (StaleQueue, ValueError) as exc:
        raise _queue_error(exc) from exc


@router.post("/scheduler/queue/release")
async def scheduler_queue_release(body: QueueRelease):
    try:
        return await DEVELOPMENT.release_pin(body.item_id, expected_revision=body.expected_revision)
    except (StaleQueue, ValueError) as exc:
        raise _queue_error(exc) from exc


@router.post("/scheduler/queue/undo")
async def scheduler_queue_undo(body: QueueUndo):
    try:
        return await DEVELOPMENT.undo(body.history_id, expected_revision=body.expected_revision, actor=OWNER)
    except (StaleQueue, ValueError) as exc:
        raise _queue_error(exc) from exc


@router.put("/scheduler/away")
async def scheduler_away(body: AwayToggle):
    try:
        return await DEVELOPMENT.set_away(body.enabled, actor=OWNER, reason="Turned off by the owner")
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/scheduler/deliveries/{delivery_id}/publish")
async def scheduler_publish(delivery_id: str):
    try:
        return await DEVELOPMENT.request_publish(delivery_id)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/scheduler/builds/{merge_sha}/retry")
async def scheduler_build_retry(merge_sha: str):
    try:
        return await DEVELOPMENT.retry_build(merge_sha)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.put("/scheduler")
async def scheduler_config(body: DevelopmentConfig):
    try:
        return await DEVELOPMENT.configure(body)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/scheduler/scan")
async def scheduler_scan():
    try:
        return await DEVELOPMENT.scan()
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/scheduler/drive-import")
async def scheduler_drive_import(body: DriveRfcImport):
    try:
        return await DEVELOPMENT.import_drive(body.file_id, body.title, body.content)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/scheduler/items/{item_id}")
async def scheduler_select(item_id: str, body: RfcSelection):
    try:
        return await DEVELOPMENT.select(item_id, body.revision, body.queued)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/scheduler/run")
async def scheduler_run():
    try:
        await DEVELOPMENT.scan()
        return await DEVELOPMENT.launch()
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/scheduler/stop")
async def scheduler_stop():
    return await DEVELOPMENT.stop()


@router.post("/scheduler/runs/{run_id}/decision")
async def scheduler_decision(run_id: str, body: MissionDecision):
    try:
        return await DEVELOPMENT.command(run_id, body.task_id, body.expected_payload, body.approved)
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


class StartBody(BaseModel):
    repo: str | None = None
    run_baseline: bool = True


class CheckpointBody(BaseModel):
    message: str = "jarvis checkpoint"


class StopBody(BaseModel):
    reason: str = "Emergency stop"


class MergeBody(BaseModel):
    target_branch: str = "main"


def _http_error(exc: Exception) -> HTTPException:
    if isinstance(exc, KillSwitchActive):
        return HTTPException(409, str(exc))
    if isinstance(exc, WorktreeError):
        return HTTPException(400, str(exc))
    if isinstance(exc, PermissionError):
        return HTTPException(403, str(exc))
    return HTTPException(500, str(exc))


@router.get("")
async def self_dev_status():
    return snapshot()


@router.post("/start")
async def start_self_dev(body: StartBody | None = None):
    body = body or StartBody()
    try:
        from ..recovery.hooks import RISK_SELF_IMPROVEMENT, ensure_checkpoint_before_risk

        ensure_checkpoint_before_risk(RISK_SELF_IMPROVEMENT, notes="self-dev trial start")
        return start_trial(repo=body.repo, run_baseline=body.run_baseline)
    except (KillSwitchActive, WorktreeError, PermissionError) as exc:
        raise _http_error(exc) from exc


@router.post("/stop")
async def stop_self_dev(body: StopBody | None = None):
    body = body or StopBody()
    return activate_kill_switch(body.reason)


@router.post("/resume")
async def resume_self_dev():
    return clear_kill_switch()


@router.get("/worktrees/{worktree_id}")
async def get_one_worktree(worktree_id: str):
    try:
        spec = get_worktree(worktree_id)
        status = worktree_status(spec.path)
        return {**spec.as_dict(), "git": status}
    except WorktreeError as exc:
        raise _http_error(exc) from exc


@router.post("/worktrees/{worktree_id}/checkpoint")
async def checkpoint(worktree_id: str, body: CheckpointBody | None = None):
    body = body or CheckpointBody()
    try:
        spec = get_worktree(worktree_id)
        result = checkpoint_commit(spec.path, body.message)
        from ..agent.self_dev import load_session, save_session

        session = load_session()
        if session and result.get("created"):
            usage = session.setdefault("usage", {})
            commits = list(usage.get("commits") or [])
            commits.append(result["commit"])
            usage["commits"] = commits
            note_activity(session, f"Created checkpoint {result['commit'][:12]}", state="waiting")
            save_session(session)
        return result
    except (WorktreeError, PermissionError) as exc:
        raise _http_error(exc) from exc


@router.post("/worktrees/{worktree_id}/verify")
async def verify_worktree(worktree_id: str):
    try:
        return run_verification_gate(worktree_id)
    except WorktreeError as exc:
        raise _http_error(exc) from exc


@router.post("/worktrees/{worktree_id}/discard")
async def discard(worktree_id: str):
    try:
        return discard_worktree(worktree_id).as_dict()
    except WorktreeError as exc:
        raise _http_error(exc) from exc


@router.post("/report")
async def end_of_run_report():
    return build_report()


@router.get("/experimental-launch")
async def experimental_launch():
    state = snapshot()
    return experimental_launch_plan(state.get("worktree_path"))


@router.post("/merge")
async def forbidden_merge(body: MergeBody | None = None):
    body = body or MergeBody()
    try:
        refuse_trusted_merge(body.target_branch)
    except PermissionError as exc:
        raise _http_error(exc) from exc
