from __future__ import annotations

import json

import uuid

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..agent.skills import (
    bind_parameters,
    execute_bound_skill,
    has_secret_parameters,
    instantiate_steps,
    normalize_parameters,
    promote_from_trajectories,
    skill_is_runnable,
    steps_are_executable,
)
from ..db.models import Skill, Trajectory
from ..db.session import SessionLocal
from ..tools.registry import REGISTRY

router = APIRouter(prefix="/api/memory", tags=["memory"])


class SkillIn(BaseModel):
    name: str
    description: str = ""
    task_class: str = ""
    parameters: list[Any] = []
    tools: list[str] = []
    steps: list[Any] = []
    verification: str = ""
    recovery: str = ""


class SkillRunIn(BaseModel):
    goal: str = ""
    parameters: dict = {}


def _skill_dict(skill: Skill) -> dict:
    steps = json.loads(skill.steps_json or "[]")
    bound_now = steps_are_executable([step for step in steps if isinstance(step, dict)])
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "task_class": skill.task_class,
        "parameters": normalize_parameters(skill.parameters_json),
        "tools": json.loads(skill.tools_json or "[]"),
        "steps": steps,
        "verification": skill.verification,
        "recovery": skill.recovery,
        "origin": skill.origin,
        "times_used": skill.times_used,
        "enabled": skill.enabled,
        "executable": bound_now or skill_is_runnable(skill),
        "runnable": skill_is_runnable(skill),
        "requires_secret": has_secret_parameters(skill),
        "created_at": skill.created_at.isoformat() if skill.created_at else None,
    }


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


@router.get("/skills")
async def list_skills():
    async with SessionLocal() as session:
        rows = (await session.execute(select(Skill).order_by(Skill.created_at.desc()))).scalars().all()
    return [_skill_dict(row) for row in rows]


@router.post("/skills")
async def create_skill(body: SkillIn):
    async with SessionLocal() as session:
        clash = (await session.execute(select(Skill).where(Skill.name == body.name))).scalar_one_or_none()
        if clash:
            raise HTTPException(409, f"A skill named {body.name} already exists")
        skill = Skill(
            id=str(uuid.uuid4()),
            name=body.name,
            description=body.description,
            task_class=body.task_class,
            parameters_json=json.dumps(body.parameters),
            tools_json=json.dumps(body.tools),
            steps_json=json.dumps(body.steps),
            verification=body.verification,
            recovery=body.recovery,
            origin="manual",
        )
        session.add(skill)
        await session.commit()
        return _skill_dict(skill)


@router.post("/skills/promote")
async def promote_skills():
    created = await promote_from_trajectories()
    return {"created": [skill.name for skill in created]}


@router.post("/skills/{skill_id}/run")
async def run_skill(skill_id: str, body: SkillRunIn | None = None):
    body = body or SkillRunIn()
    async with SessionLocal() as session:
        skill = await session.get(Skill, skill_id)
        if not skill:
            raise HTTPException(404, "Skill not found")
        if not skill.enabled:
            raise HTTPException(400, "Skill is disabled")
        bound = bind_parameters(skill, body.goal, body.parameters)
        if bound is None:
            raise HTTPException(400, "Could not bind skill parameters from the goal. Pass them explicitly.")
        steps = instantiate_steps(skill, bound)
        if not steps_are_executable(steps):
            raise HTTPException(400, "This skill still only guides the model; it has no executable parameterized steps.")
        skill.times_used += 1
        await session.commit()

    async def _run(name: str, arguments: dict):
        return await REGISTRY.execute(name, arguments)

    results = await execute_bound_skill(steps, _run)
    success = bool(results) and all(item.get("success") for item in results)
    return {
        "ok": success,
        "skill": skill.name,
        "parameters": bound,
        "results": [
            {
                "tool": item.get("tool"),
                "success": item.get("success"),
                "output": (item.get("output") or "")[:4000],
                "error": item.get("error") or "",
            }
            for item in results
        ],
    }


@router.post("/skills/{skill_id}/{state}")
async def set_skill_state(skill_id: str, state: str):
    if state not in {"enable", "disable"}:
        raise HTTPException(400, "state must be enable or disable")
    async with SessionLocal() as session:
        skill = await session.get(Skill, skill_id)
        if not skill:
            raise HTTPException(404, "Skill not found")
        skill.enabled = state == "enable"
        await session.commit()
        return _skill_dict(skill)


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str):
    async with SessionLocal() as session:
        skill = await session.get(Skill, skill_id)
        if not skill:
            raise HTTPException(404, "Skill not found")
        await session.delete(skill)
        await session.commit()
    return {"ok": True}
