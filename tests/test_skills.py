import json

from sqlalchemy import select

from app.agent.planning import WorkingState
from app.agent.skills import as_prompt_block, promote_from_trajectories, relevant_skills
from app.agent.trajectory import record_trajectory
from app.db.models import Skill, Task, ToolCallRecord
from app.db.session import SessionLocal


async def _completed_task(index: int, goal: str, task_class: str, tools: list[str]) -> None:
    task_id = f"task-{index}"
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title=goal, prompt=goal, task_class=task_class, verification="reopened the workbook"))
        for tool in tools:
            session.add(ToolCallRecord(task_id=task_id, tool_name=tool, success=True, output="ok"))
        await session.commit()
    await record_trajectory(task_id, WorkingState(goal=goal, task_class=task_class), "completed")


async def test_one_off_success_does_not_become_a_skill(jarvis_env):
    await _completed_task(1, "export research comparison to excel", "office", ["python", "filesystem"])
    assert await promote_from_trajectories() == []


async def test_repeated_stable_workflow_is_promoted_once(jarvis_env):
    for index in range(3):
        await _completed_task(index, "export research comparison to excel", "office", ["python", "filesystem"])

    created = await promote_from_trajectories()
    assert len(created) == 1
    skill = created[0]
    assert json.loads(skill.tools_json) == ["python", "filesystem"]
    assert skill.task_class == "office"
    assert "reopened the workbook" in skill.verification
    assert skill.origin == "promoted"

    assert await promote_from_trajectories() == []
    async with SessionLocal() as session:
        assert len((await session.execute(select(Skill))).scalars().all()) == 1


async def test_promoted_skill_is_offered_to_a_matching_task(jarvis_env):
    for index in range(3):
        await _completed_task(index, "export research comparison to excel", "office", ["python", "filesystem"])
    await promote_from_trajectories()

    picked = await relevant_skills("office", "export another research comparison to excel")
    assert len(picked) == 1
    block = as_prompt_block(picked)
    assert "Reusable skills already proven" in block
    assert "Steps:" in block and "python" in block

    assert await relevant_skills("browser", "log into the router") == []

    async with SessionLocal() as session:
        stored = (await session.execute(select(Skill))).scalars().all()
    assert stored[0].times_used == 1


async def test_disabled_skill_is_not_offered(jarvis_env):
    for index in range(3):
        await _completed_task(index, "export research comparison to excel", "office", ["python", "filesystem"])
    await promote_from_trajectories()
    async with SessionLocal() as session:
        skill = (await session.execute(select(Skill))).scalars().one()
        skill.enabled = False
        await session.commit()

    assert await relevant_skills("office", "export research comparison to excel") == []
