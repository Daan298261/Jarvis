from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..trajectories.adapters.cursor import TrajectoryAdapterError, parse_cursor_transcript
from ..trajectories.consumer import ensure_consumer_started, enqueue_trajectory, peek_pending_trajectories
from ..trajectories.native import emit_from_task_id
from ..trajectories.store import get_trajectory, list_trajectories, save_trajectory

router = APIRouter(prefix="/api/trajectories", tags=["trajectories"])


class CursorImportIn(BaseModel):
    transcript: str
    source_uri: str | None = None
    model: str | None = None
    repository: str | None = None
    branch: str | None = None
    workspace_path: str | None = None


class NativeEmitIn(BaseModel):
    task_id: str
    model: str | None = None


@router.get("")
async def list_imported_trajectories(limit: int = 50):
    return list_trajectories(limit=limit)


@router.get("/queue/pending")
async def pending_consumer_queue():
    items = peek_pending_trajectories()
    return [{"trajectory_id": item.trajectory_id, "harness": item.provenance.harness} for item in items]


@router.post("/import/cursor")
async def import_cursor_transcript(body: CursorImportIn):
    ensure_consumer_started()
    try:
        trajectory = parse_cursor_transcript(
            body.transcript,
            source_uri=body.source_uri,
            import_id=str(uuid.uuid4()),
            model=body.model,
            repository=body.repository,
            branch=body.branch,
            workspace_path=body.workspace_path,
        )
    except TrajectoryAdapterError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    saved = save_trajectory(trajectory)
    enqueue_trajectory(saved)
    return {
        "trajectory_id": saved.trajectory_id,
        "harness": saved.provenance.harness,
        "event_count": len(saved.events),
        "outcome": saved.outcome.model_dump(mode="json"),
        "trusted": saved.provenance.trusted,
    }


@router.post("/emit/native")
async def emit_native_trajectory(body: NativeEmitIn):
    ensure_consumer_started()
    saved = await emit_from_task_id(body.task_id, model=body.model)
    if not saved:
        raise HTTPException(status_code=404, detail="No native trajectory for task")
    return {
        "trajectory_id": saved.trajectory_id,
        "harness": saved.provenance.harness,
        "trusted": saved.provenance.trusted,
    }


@router.get("/{trajectory_id}")
async def inspect_trajectory(trajectory_id: str):
    trajectory = get_trajectory(trajectory_id)
    if not trajectory:
        raise HTTPException(status_code=404, detail="Trajectory not found")
    return trajectory.model_dump(mode="json")
