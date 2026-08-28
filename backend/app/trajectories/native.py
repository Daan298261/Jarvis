from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from ..db.models import Trajectory
from .schema import (
    CandidateSkill,
    JarvisTrajectoryV1,
    TrajectoryEvent,
    TrajectoryOutcome,
    TrajectoryProvenance,
    TrajectoryVerification,
)
from .store import new_trajectory_id


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def from_native_trajectory(row: Trajectory, *, model: str | None = None) -> JarvisTrajectoryV1:
    """Convert a native Jarvis DB trajectory row into JarvisTrajectoryV1."""
    tools = json.loads(row.tools_json or "[]")
    steps = json.loads(row.steps_json or "[]")
    created = row.created_at.isoformat() if row.created_at else _utc_now()

    events: list[TrajectoryEvent] = []
    failures: list[str] = []
    for index, step in enumerate(steps if isinstance(steps, list) else []):
        if not isinstance(step, dict):
            continue
        tool_name = str(step.get("tool") or "unknown")
        ok = bool(step.get("ok"))
        if not ok and step.get("problem"):
            failures.append(f"{tool_name}: {step['problem']}")
        events.append(
            TrajectoryEvent(
                sequence=index,
                timestamp=created,
                event_type="tool_result" if "ok" in step else "tool_call",
                tool_name=tool_name,
                tool_args=step.get("arguments") if isinstance(step.get("arguments"), dict) else None,
                tool_result=step.get("problem") if not ok else "ok",
                success=ok,
                metadata={"native_step": True},
            )
        )

    verified = row.outcome == "completed" and bool((row.verification or "").strip())
    outcome = TrajectoryOutcome(
        status=row.outcome or "attempted",
        attempted=True,
        verified=verified,
        summary=row.goal,
    )
    verification = TrajectoryVerification(
        attempted=bool((row.verification or "").strip()),
        passed=verified,
        details=(row.verification or "")[:1000] or None,
    )

    candidate_skills: list[CandidateSkill] = []
    if tools and row.outcome == "completed":
        candidate_skills.append(
            CandidateSkill(
                tools=[str(tool) for tool in tools],
                description=row.goal,
                confidence=0.7 if verified else 0.3,
            )
        )

    return JarvisTrajectoryV1(
        trajectory_id=new_trajectory_id(),
        goal=row.goal,
        task_class=row.task_class,
        provenance=TrajectoryProvenance(
            harness="jarvis",
            model=model,
            source_uri=f"task:{row.task_id}",
            source_format="native-db",
            imported_at=_utc_now(),
            import_id=row.task_id,
            trusted=True,
        ),
        events=events,
        outcome=outcome,
        verification=verification,
        failures=failures or ([row.failures] if row.failures else []),
        recovery=row.recovery or None,
        candidate_skills=candidate_skills,
        duration_seconds=float(row.duration_seconds or 0),
    )


async def emit_from_task_id(task_id: str, *, model: str | None = None) -> JarvisTrajectoryV1 | None:
    from sqlalchemy import select

    from ..db.models import Trajectory
    from ..db.session import SessionLocal
    from .consumer import enqueue_trajectory
    from .store import save_trajectory

    async with SessionLocal() as session:
        row = (
            await session.execute(
                select(Trajectory).where(Trajectory.task_id == task_id).order_by(Trajectory.id.desc())
            )
        ).scalars().first()
    if not row:
        return None
    trajectory = from_native_trajectory(row, model=model)
    saved = save_trajectory(trajectory)
    enqueue_trajectory(saved)
    return saved
