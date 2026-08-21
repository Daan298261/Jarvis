from __future__ import annotations

import json

import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlalchemy import select

from ..agent.skills import promote_from_trajectories
from ..db.models import Skill, Trajectory
from ..db.session import SessionLocal

router = APIRouter(prefix="/api/memory", tags=["memory"])


class SkillIn(BaseModel):
    name: str
    description: str = ""
    task_class: str = ""
    parameters: list[str] = []
    tools: list[str] = []
    steps: list[str] = []
    verification: str = ""
    recovery: str = ""


def _skill_dict(skill: Skill) -> dict:
    return {
        "id": skill.id,
        "name": skill.name,
        "description": skill.description,
        "task_class": skill.task_class,
        "parameters": json.loads(skill.parameters_json or "[]"),
        "tools": json.loads(skill.tools_json or "[]"),
        "steps": json.loads(skill.steps_json or "[]"),
        "verification": skill.verification,
        "recovery": skill.recovery,
        "origin": skill.origin,
        "times_used": skill.times_used,
        "enabled": skill.enabled,
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
