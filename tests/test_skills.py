import json

from sqlalchemy import select

from app.agent.loop import AGENT
from app.agent.planning import WorkingState
from app.agent.prompts import VERIFY_PROMPT
from app.agent.skills import (
    as_prompt_block,
    bind_parameters,
    execute_bound_skill,
    instantiate_steps,
    promote_from_trajectories,
    relevant_skills,
    steps_are_executable,
)
from app.agent.trajectory import record_trajectory
from app.db.models import Skill, Task, ToolCallRecord
from app.db.session import SessionLocal
from app.providers.base import ChatResult
from app.tools.registry import REGISTRY


def _tool(name: str, arguments: dict, call_id: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class ScriptedProvider:
    def __init__(self, turns):
        self.turns = list(turns)
        self.calls = []

    async def health(self):
        return True

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append(messages)
        if not self.turns:
            return ChatResult(content="Final report.")
        return self.turns.pop(0)


async def _completed_task(
    index: int,
    goal: str,
    task_class: str,
    tools: list[str],
    arguments_list: list[dict] | None = None,
    prefix: str = "task",
) -> None:
    task_id = f"{prefix}-{index}"
    async with SessionLocal() as session:
        session.add(Task(id=task_id, title=goal, prompt=goal, task_class=task_class, verification="reopened the workbook"))
        for offset, tool in enumerate(tools):
            arguments = {}
            if arguments_list and offset < len(arguments_list):
                arguments = arguments_list[offset]
            session.add(
                ToolCallRecord(
                    task_id=task_id,
                    tool_name=tool,
                    success=True,
                    output="ok",
                    arguments_json=json.dumps(arguments),
                )
            )
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


async def test_parameterized_skill_binds_path_and_runs(jarvis_env):
    tmp = jarvis_env["tmp"]
    paths = [tmp / f"notes-{index}.txt" for index in range(3)]
    for index, path in enumerate(paths):
        await _completed_task(
            index,
            f"organize files and write notes to {path}",
            "filesystem",
            ["filesystem"],
            [{"action": "write", "path": str(path), "content": "READY", "create_backup": False}],
            prefix="param",
        )

    created = await promote_from_trajectories()
    assert len(created) == 1
    skill = created[0]
    params = json.loads(skill.parameters_json)
    names = {item["name"] for item in params if isinstance(item, dict)}
    assert "path" in names
    steps = json.loads(skill.steps_json)
    assert steps[0]["arguments"]["path"] == "{path}"
    assert steps[0]["arguments"]["content"] == "READY"

    target = tmp / "final-notes.txt"
    bound = bind_parameters(skill, f"organize files and write notes to {target}")
    assert bound is not None
    assert bound["path"] == str(target)
    instantiated = instantiate_steps(skill, bound)
    assert steps_are_executable(instantiated)

    results = await execute_bound_skill(instantiated, REGISTRY.execute)
    assert results[0]["success"] is True
    assert target.read_text(encoding="utf-8") == "READY"


async def test_matching_task_auto_executes_parameterized_skill(jarvis_env):
    tmp = jarvis_env["tmp"]
    for index in range(3):
        path = tmp / f"auto-{index}.txt"
        await _completed_task(
            index,
            f"organize files and write notes to {path}",
            "filesystem",
            ["filesystem"],
            [{"action": "write", "path": str(path), "content": "SKILL", "create_backup": False}],
            prefix="auto",
        )
    await promote_from_trajectories()

    target = tmp / "auto-final.txt"
    provider = ScriptedProvider(
        [
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "v1")]),
            ChatResult(content="Verified the notes file contains SKILL."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"organize files and write notes to {target}",
        autonomy="autonomous",
        profile="fast",
        execution_mode="balanced",
    )
    await AGENT._tasks[created.id]
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "SKILL"
    async with SessionLocal() as session:
        task = await session.get(Task, created.id)
    assert task.status == "completed"
    assert "SKILL" in (task.verification or task.result or "")
    assert any(
        any(getattr(message, "content", None) == VERIFY_PROMPT for message in call)
        for call in provider.calls
    )
