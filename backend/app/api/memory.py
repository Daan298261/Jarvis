from __future__ import annotations

import json

from fastapi import APIRouter
from sqlalchemy import select

from ..db.models import Trajectory
from ..db.session import SessionLocal

router = APIRouter(prefix="/api/memory", tags=["memory"])


@router.get("/trajectories")
async def list_trajectories(limit: int = 50):
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(Trajectory).order_by(Trajectory.created_at.desc()).limit(limit))
        ).scalars().all()
    return [
        {
            "id": row.id,
            "task_id": row.task_id,
            "task_class": row.task_class,
            "goal": row.goal,
            "outcome": row.outcome,
            "tools": json.loads(row.tools_json or "[]"),
            "steps": json.loads(row.steps_json or "[]"),
            "recovery": row.recovery,
            "failures": row.failures,
            "duration_seconds": row.duration_seconds,
            "reuse_count": row.reuse_count,
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]
