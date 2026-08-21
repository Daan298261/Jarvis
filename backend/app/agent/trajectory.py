from __future__ import annotations

import json
import re
from typing import Any, Iterable

from sqlalchemy import select

from ..db.models import Task, ToolCallRecord, Trajectory
from ..db.session import SessionLocal
from .planning import WorkingState
from .recovery import classify_failure

STOPWORDS = {
    "the", "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "this", "that", "these", "those",
    "it", "its", "is", "are", "be", "then", "make", "sure", "please", "do", "does", "my", "me", "i", "you",
    "create", "write", "file", "files", "into", "from", "at", "as", "by", "not", "no", "if", "so", "up",
}

MAX_PROMPT_ENTRIES = 3


def keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9._-]{2,}", (text or "").lower())
    return {word for word in words if word not in STOPWORDS}


def _score(row: Trajectory, task_class: str, goal_keywords: set[str]) -> float:
    score = 0.0
    if row.task_class and row.task_class == task_class:
        score += 2.0
    overlap = keywords(row.goal) & goal_keywords
    score += float(len(overlap))
    if row.outcome == "completed":
        score += 1.5
    return score


async def record_trajectory(task_id: str, working: WorkingState, outcome: str) -> Trajectory | None:
    """Persist an actionable summary of a finished task."""
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        if not task:
            return None
        calls = (
            await session.execute(
                select(ToolCallRecord).where(ToolCallRecord.task_id == task_id).order_by(ToolCallRecord.id)
            )
        ).scalars().all()

        steps: list[dict[str, Any]] = []
        ordered_tools: list[str] = []
        for call in calls:
            entry: dict[str, Any] = {"tool": call.tool_name, "ok": bool(call.success)}
            if not call.success:
                entry["problem"] = classify_failure(call.error or call.output)
            steps.append(entry)
            if call.tool_name not in ordered_tools:
                ordered_tools.append(call.tool_name)

        succeeded = [step["tool"] for step in steps if step["ok"]]
        recovery = ""
        for index, step in enumerate(steps):
            if not step["ok"]:
                later = next((s["tool"] for s in steps[index + 1 :] if s["ok"]), "")
                if later and later != step["tool"]:
                    recovery = f"{step['tool']} failed ({step.get('problem')}), {later} worked instead"
                    break

        row = Trajectory(
            task_id=task_id,
            task_class=task.task_class or working.task_class,
            goal=(working.goal or task.title)[:400],
            outcome=outcome,
            tools_json=json.dumps(ordered_tools),
            steps_json=json.dumps(steps[:60]),
            failures="\n".join(working.known_failures[-4:])[:2000],
            recovery=recovery,
            verification=(task.verification or "")[:1000],
            duration_seconds=task.duration_seconds or 0,
        )
        session.add(row)
        await session.commit()
        return row


async def relevant_trajectories(task_class: str, goal: str, limit: int = MAX_PROMPT_ENTRIES) -> list[Trajectory]:
    goal_keywords = keywords(goal)
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(Trajectory).order_by(Trajectory.created_at.desc()).limit(200))
        ).scalars().all()
        scored = [(row, _score(row, task_class, goal_keywords)) for row in rows]
        picked = [row for row, score in sorted(scored, key=lambda item: item[1], reverse=True) if score >= 2.0][:limit]
        for row in picked:
            row.reuse_count += 1
        if picked:
            await session.commit()
        return picked


def as_prompt_block(rows: Iterable[Trajectory]) -> str:
    entries = []
    for row in rows:
        tools = ", ".join(json.loads(row.tools_json or "[]")) or "none"
        line = f"- {row.goal} -> {row.outcome} using {tools}"
        if row.recovery:
            line += f". Recovery: {row.recovery}"
        entries.append(line)
    if not entries:
        return ""
    return (
        "Lessons from similar earlier tasks on this machine. Reuse what worked and avoid repeating what failed:\n"
        + "\n".join(entries)
    )
