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
    refuse_trusted_merge,
    run_verification_gate,
    snapshot,
    start_trial,
)
from ..agent.worktrees import WorktreeError, discard_worktree, get_worktree, worktree_status

router = APIRouter(prefix="/api/self-dev", tags=["self-dev"])


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
