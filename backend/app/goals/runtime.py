"""Minimal Goal Runtime facade for Skill Forge routing hooks (RFC-0173).

Full GoalRun lifecycle remains RFC-0016. This module exposes the public surface
Skill Forge and personas call today: attach ranked owner-approved skills to a goal.
"""

from __future__ import annotations

from typing import Any

from ..skills.routing import goal_runtime_skill_context, search_skills


def suggest_skills_for_goal(
    goal_id: str,
    objective: str,
    *,
    persona_id: str | None = None,
    task_class: str = "",
    limit: int = 5,
) -> dict[str, Any]:
    hits = search_skills(
        objective,
        persona_id=persona_id,
        goal_id=goal_id,
        task_class=task_class or None,
        limit=limit,
    )
    context = goal_runtime_skill_context(goal_id, objective, task_class=task_class)
    return {
        "goal_id": goal_id,
        "objective": objective,
        "persona_id": persona_id,
        "skills": hits,
        "prompt_block": context.get("prompt_block") or "",
    }
