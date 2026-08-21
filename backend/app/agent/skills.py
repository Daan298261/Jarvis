from __future__ import annotations

import json
import re
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Iterable

from sqlalchemy import select

from ..db.models import Skill, Trajectory, utcnow
from ..db.session import SessionLocal
from .trajectory import keywords

MIN_REPEATS = 3
MAX_PROMPT_SKILLS = 2


@dataclass
class SkillCandidate:
    task_class: str
    tools: tuple[str, ...]
    goals: list[str] = field(default_factory=list)
    verifications: list[str] = field(default_factory=list)

    @property
    def occurrences(self) -> int:
        return len(self.goals)


def _skill_name(goals: Iterable[str], task_class: str) -> str:
    counter: Counter[str] = Counter()
    for goal in goals:
        counter.update(keywords(goal))
    words = [word for word, _ in counter.most_common(3)]
    if not words:
        words = [task_class or "task"]
    slug = "_".join(re.sub(r"[^a-z0-9]+", "", word) for word in words if word)
    return slug[:80] or "reusable_workflow"


async def promote_from_trajectories(min_repeats: int = MIN_REPEATS) -> list[Skill]:
    """Turn repeated, stable, successful workflows into skills.

    A workflow only becomes a skill once the same task class has been solved
    with the same tool sequence several times. One-off successes stay as
    trajectory memory.
    """
    created: list[Skill] = []
    async with SessionLocal() as session:
        rows = (await session.execute(select(Trajectory).where(Trajectory.outcome == "completed"))).scalars().all()
        existing = (await session.execute(select(Skill))).scalars().all()
        known = {(skill.task_class, tuple(json.loads(skill.tools_json or "[]"))) for skill in existing}
        used_names = {skill.name for skill in existing}

        groups: dict[tuple[str, tuple[str, ...]], SkillCandidate] = defaultdict(lambda: SkillCandidate("", ()))
        for row in rows:
            tools = tuple(json.loads(row.tools_json or "[]"))
            if not tools:
                continue
            key = (row.task_class or "", tools)
            candidate = groups[key]
            candidate.task_class, candidate.tools = key
            candidate.goals.append(row.goal)
            if row.verification:
                candidate.verifications.append(row.verification)

        for key, candidate in groups.items():
            if candidate.occurrences < min_repeats or key in known:
                continue
            name = _skill_name(candidate.goals, candidate.task_class)
            if name in used_names:
                name = f"{name}_{len(used_names) + 1}"
            used_names.add(name)
            skill = Skill(
                id=str(uuid.uuid4()),
                name=name,
                description=(
                    f"Repeatable {candidate.task_class or 'workflow'} solved {candidate.occurrences} times "
                    f"with {', '.join(candidate.tools)}. Example goal: {candidate.goals[0][:200]}"
                ),
                task_class=candidate.task_class,
                parameters_json=json.dumps(sorted(keywords(" ".join(candidate.goals)))[:6]),
                tools_json=json.dumps(list(candidate.tools)),
                steps_json=json.dumps([f"use {tool}" for tool in candidate.tools]),
                verification=(candidate.verifications[0] if candidate.verifications else "")[:1000],
                recovery="Fall back to the alternatives suggested for the failing tool.",
                origin="promoted",
            )
            session.add(skill)
            created.append(skill)
        if created:
            await session.commit()
    return created


async def relevant_skills(task_class: str, goal: str, limit: int = MAX_PROMPT_SKILLS) -> list[Skill]:
    goal_keywords = keywords(goal)
    async with SessionLocal() as session:
        rows = (await session.execute(select(Skill).where(Skill.enabled.is_(True)))).scalars().all()
        scored: list[tuple[Skill, float]] = []
        for row in rows:
            score = 2.0 if row.task_class and row.task_class == task_class else 0.0
            score += float(len(keywords(f"{row.name} {row.description}") & goal_keywords))
            if score >= 2.0:
                scored.append((row, score))
        picked = [row for row, _ in sorted(scored, key=lambda item: item[1], reverse=True)][:limit]
        for row in picked:
            row.times_used += 1
            row.updated_at = utcnow()
        if picked:
            await session.commit()
        return picked


def as_prompt_block(skills: Iterable[Skill]) -> str:
    entries = []
    for skill in skills:
        steps = ", ".join(json.loads(skill.steps_json or "[]"))
        line = f"- {skill.name}: {skill.description}"
        if steps:
            line += f"\n  Steps: {steps}"
        if skill.verification:
            line += f"\n  Verify: {skill.verification[:200]}"
        entries.append(line)
    if not entries:
        return ""
    return (
        "Reusable skills already proven on this machine. Follow one when it fits instead of rediscovering the workflow:\n"
        + "\n".join(entries)
    )
