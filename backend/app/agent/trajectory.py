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

MAX_PROMPT_ENTRIES = 2
LESSONS_HEADER = (
    "Lessons from similar earlier tasks on this machine. Reuse what worked and avoid repeating what failed:"
)
LESSONS_TOKEN_CAP = 200

_DENYLIST_GOAL = re.compile(
    r"(?i)\b("
    r"what was my last message|what did i just say|what was my previous message|"
    r"repeat what i said|what did you just say"
    r")\b"
)
_SECRET_SHAPE = re.compile(
    r"(?i)(api[_-]?key|password|secret|bearer\s+[a-z0-9._-]{8,}|sk-[a-z0-9]{8,})"
)


def keywords(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9][a-z0-9._-]{2,}", (text or "").lower())
    return {word for word in words if word not in STOPWORDS}


def _overlap_count(row: Trajectory, goal_keywords: set[str]) -> int:
    return len(keywords(row.goal) & goal_keywords)


def _score(row: Trajectory, task_class: str, goal_keywords: set[str]) -> float:
    overlap = float(_overlap_count(row, goal_keywords))
    if overlap < 1.0:
        return 0.0
    score = overlap
    if row.task_class and row.task_class == task_class:
        score += 0.5
    if row.outcome == "completed":
        score += 1.0
    if row.recovery:
        score += 0.5
    return score


def _tools_list(row: Trajectory) -> list[str]:
    try:
        return list(json.loads(row.tools_json or "[]"))
    except json.JSONDecodeError:
        return []


def _denylist_reason(row: Trajectory) -> str | None:
    goal = (row.goal or "").strip()
    if not goal:
        return "empty_goal"
    if _DENYLIST_GOAL.search(goal):
        return "last_message_loop"
    if _SECRET_SHAPE.search(goal):
        return "credential_shaped"
    tools = _tools_list(row)
    if not tools or tools == ["none"]:
        if not (row.recovery or "").strip() and not (row.verification or "").strip():
            return "tools_none_trivia"
    return None


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
            try:
                arguments = json.loads(call.arguments_json or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if isinstance(arguments, dict) and arguments:
                compact = {}
                for key, value in arguments.items():
                    text = value if isinstance(value, str) else json.dumps(value, default=str)
                    compact[key] = text[:240]
                entry["arguments"] = compact
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
        try:
            from ..trajectories.native import from_native_trajectory
            from ..trajectories.consumer import enqueue_trajectory
            from ..trajectories.store import save_trajectory

            enqueue_trajectory(save_trajectory(from_native_trajectory(row)))
        except Exception:
            pass
        return row


async def relevant_trajectories(task_class: str, goal: str, limit: int = MAX_PROMPT_ENTRIES) -> list[Trajectory]:
    goal_keywords = keywords(goal)
    if not goal_keywords:
        return []
    async with SessionLocal() as session:
        rows = (
            await session.execute(select(Trajectory).order_by(Trajectory.created_at.desc()).limit(200))
        ).scalars().all()
        scored: list[tuple[Trajectory, float]] = []
        for row in rows:
            reason = _denylist_reason(row)
            if reason:
                continue
            score = _score(row, task_class, goal_keywords)
            if score < 2.0:
                continue
            scored.append((row, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        seen_goals: set[str] = set()
        picked: list[Trajectory] = []
        for row, _ in scored:
            key = (row.goal or "").strip().lower()
            if key in seen_goals:
                continue
            seen_goals.add(key)
            picked.append(row)
            if len(picked) >= limit:
                break
        for row in picked:
            row.reuse_count += 1
        if picked:
            await session.commit()
        return picked


def as_prompt_block(rows: Iterable[Trajectory]) -> str:
    entries = []
    for row in rows:
        tools = ", ".join(_tools_list(row)) or "none"
        line = f"- {row.goal} -> {row.outcome} using {tools}"
        if row.recovery:
            line += f". Recovery: {row.recovery}"
        entries.append(line)
    if not entries:
        return ""
    block = LESSONS_HEADER + "\n" + "\n".join(entries)
    from ..inference.prompt_budget import estimate_text_tokens

    if estimate_text_tokens(block) > LESSONS_TOKEN_CAP:
        trimmed: list[str] = []
        for line in entries:
            candidate = LESSONS_HEADER + "\n" + "\n".join(trimmed + [line])
            if estimate_text_tokens(candidate) > LESSONS_TOKEN_CAP:
                break
            trimmed.append(line)
        if not trimmed:
            return ""
        block = LESSONS_HEADER + "\n" + "\n".join(trimmed)
    return block


async def gated_trajectory_lessons(
    task_class: str,
    goal: str,
    *,
    remaining_token_budget: int | None = None,
) -> tuple[str, list[Trajectory], list[str]]:
    """Quality-gated lessons block; returns (block, injected rows, drop reasons)."""
    dropped: list[str] = []
    goal_keywords = keywords(goal)
    if not goal_keywords:
        return "", [], ["no_goal_keywords"]

    async with SessionLocal() as session:
        rows = (
            await session.execute(select(Trajectory).order_by(Trajectory.created_at.desc()).limit(200))
        ).scalars().all()
        scored: list[tuple[Trajectory, float]] = []
        for row in rows:
            reason = _denylist_reason(row)
            if reason:
                dropped.append(f"{reason}:{row.goal[:60]}")
                continue
            score = _score(row, task_class, goal_keywords)
            if score < 2.0:
                dropped.append(f"low_overlap:{row.goal[:60]}")
                continue
            scored.append((row, score))
        scored.sort(key=lambda item: item[1], reverse=True)
        seen_goals: set[str] = set()
        picked: list[Trajectory] = []
        for row, _ in scored:
            key = (row.goal or "").strip().lower()
            if key in seen_goals:
                dropped.append(f"duplicate:{row.goal[:60]}")
                continue
            seen_goals.add(key)
            picked.append(row)
            if len(picked) >= MAX_PROMPT_ENTRIES:
                break

    block = as_prompt_block(picked)
    if not block:
        return "", [], dropped

    if remaining_token_budget is not None:
        from ..inference.prompt_budget import estimate_text_tokens

        if estimate_text_tokens(block) > remaining_token_budget:
            dropped.append("budget_tight")
            return "", [], dropped

    if picked:
        async with SessionLocal() as session:
            for row in picked:
                db_row = await session.get(Trajectory, row.id)
                if db_row:
                    db_row.reuse_count += 1
            await session.commit()

    return block, picked, dropped
