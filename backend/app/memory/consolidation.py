from __future__ import annotations

import re
from typing import Any

from ..trajectories.schema import JarvisTrajectoryV1
from ..trajectories.store import get_trajectory, list_trajectories
from .db_layer import find_duplicate, get_repository_version
from .repository import add_entry
from .schema import ContextEntry

_NORMALIZE_RE = re.compile(r"\s+")


def _normalize_lesson(text: str) -> str:
    return _NORMALIZE_RE.sub(" ", (text or "").strip().lower())


def _is_eligible(trajectory: JarvisTrajectoryV1) -> bool:
    if not trajectory.outcome.verified:
        return False
    if trajectory.outcome.status not in {"completed", "success", "verified"}:
        return False
    if trajectory.verification is not None and not trajectory.verification.passed:
        return False
    if not trajectory.provenance.trusted and trajectory.verification is None:
        return False
    return True


def eligible_trajectories(*, limit: int = 50) -> list[JarvisTrajectoryV1]:
    """Return verified trajectories eligible for consolidation."""
    items: list[JarvisTrajectoryV1] = []
    for summary in list_trajectories(limit=limit):
        trajectory_id = summary.get("trajectory_id")
        if not trajectory_id:
            continue
        if not summary.get("outcome_verified"):
            continue
        trajectory = get_trajectory(str(trajectory_id))
        if trajectory is None:
            continue
        if _is_eligible(trajectory):
            items.append(trajectory)
    return items


def _lesson_candidates(trajectory: JarvisTrajectoryV1) -> list[dict[str, str]]:
    candidates: list[dict[str, str]] = []

    if trajectory.recovery:
        candidates.append(
            {
                "category": "lessons",
                "title": f"Recovery for {trajectory.task_class or 'task'}",
                "content": trajectory.recovery,
            }
        )

    for failure in trajectory.failures:
        text = str(failure).strip()
        if text:
            candidates.append(
                {
                    "category": "lessons",
                    "title": f"Avoid: {trajectory.task_class or 'task'} failure",
                    "content": text,
                }
            )

    for skill in trajectory.candidate_skills:
        if skill.description:
            candidates.append(
                {
                    "category": "skills",
                    "title": skill.name or f"Skill from {trajectory.task_class or 'task'}",
                    "content": skill.description,
                }
            )

    if trajectory.goal and trajectory.outcome.summary:
        candidates.append(
            {
                "category": "procedures",
                "title": f"Completed: {trajectory.goal[:120]}",
                "content": trajectory.outcome.summary,
            }
        )

    return candidates


async def consolidate_agent(
    agent_id: str,
    *,
    trajectories: list[JarvisTrajectoryV1] | None = None,
    trajectory_ids: set[str] | None = None,
) -> dict[str, Any]:
    """Run idle-time consolidation for one agent from verified trajectories."""
    source = trajectories if trajectories is not None else eligible_trajectories()
    if trajectory_ids is not None:
        source = [item for item in source if item.trajectory_id in trajectory_ids]

    version_before = await get_repository_version(agent_id)
    created: list[ContextEntry] = []
    skipped_duplicates = 0
    conflicts_flagged = 0
    processed: list[str] = []

    for trajectory in source:
        if not _is_eligible(trajectory):
            continue
        processed.append(trajectory.trajectory_id)
        for candidate in _lesson_candidates(trajectory):
            duplicate = await find_duplicate(
                agent_id,
                category=candidate["category"],
                title=candidate["title"],
                content=candidate["content"],
            )
            if duplicate is not None:
                skipped_duplicates += 1
                continue
            try:
                entry, _, _ = await add_entry(
                    agent_id,
                    category=candidate["category"],
                    title=candidate["title"],
                    content=candidate["content"],
                    source_type="consolidation",
                    source_id=trajectory.trajectory_id,
                    trajectory_id=trajectory.trajectory_id,
                    note="idle consolidation",
                    allow_duplicate=False,
                )
            except Exception:
                continue
            created.append(entry)
            if entry.conflicts_with:
                conflicts_flagged += len(entry.conflicts_with)

    version_after = await get_repository_version(agent_id)
    return {
        "agent_id": agent_id,
        "processed_trajectories": processed,
        "created_entries": [entry.id for entry in created],
        "created_count": len(created),
        "skipped_duplicates": skipped_duplicates,
        "conflicts_flagged": conflicts_flagged,
        "version_before": version_before,
        "version_after": version_after,
    }
