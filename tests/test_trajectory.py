import json

from sqlalchemy import select

from app.agent.loop import AGENT
from app.agent.planning import WorkingState
from app.agent.trajectory import as_prompt_block, record_trajectory, relevant_trajectories
from app.db.models import Task, ToolCallRecord, Trajectory
from app.db.session import SessionLocal
from app.providers.base import ChatResult


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


async def _seed_task(task_class: str, title: str) -> str:
    task = Task(id=f"seed-{title}", title=title, prompt=title, task_class=task_class, verification="checked")
    async with SessionLocal() as session:
        session.add(task)
        session.add(ToolCallRecord(task_id=task.id, tool_name="office", success=False, error="Office is not installed"))
        session.add(ToolCallRecord(task_id=task.id, tool_name="python", success=True, output="wrote workbook"))
        await session.commit()
    return task.id


async def test_trajectory_records_tools_failures_and_recovery(jarvis_env):
    task_id = await _seed_task("office", "export spreadsheet of results")
    working = WorkingState(goal="export spreadsheet of results", task_class="office")
    row = await record_trajectory(task_id, working, "completed")

    assert row is not None
    assert json.loads(row.tools_json) == ["office", "python"]
    assert "office failed" in row.recovery and "python worked instead" in row.recovery
    steps = json.loads(row.steps_json)
    assert steps[0]["ok"] is False and steps[0]["problem"] == "unavailable"


async def test_similar_task_recalls_the_trajectory(jarvis_env):
    task_id = await _seed_task("office", "export spreadsheet of results")
    await record_trajectory(task_id, WorkingState(goal="export spreadsheet of results", task_class="office"), "completed")

    picked = await relevant_trajectories("office", "export spreadsheet of quarterly results")
    assert len(picked) == 1
    block = as_prompt_block(picked)
    assert "python" in block and "Recovery" in block

    async with SessionLocal() as session:
        stored = (await session.execute(select(Trajectory))).scalars().all()
    assert stored[0].reuse_count == 1


async def test_unrelated_task_recalls_nothing(jarvis_env):
    task_id = await _seed_task("office", "export spreadsheet of results")
    await record_trajectory(task_id, WorkingState(goal="export spreadsheet of results", task_class="office"), "completed")

    assert await relevant_trajectories("browser", "log into the router admin page") == []


async def test_completed_task_writes_a_trajectory_and_later_task_sees_it(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "primes.txt"
    provider = ScriptedProvider(
        [
            ChatResult(content="END STATE: primes.txt exists\nACCEPTANCE CRITERIA:\n- file exists\nPLAN:\n1. write"),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "write", "path": str(target), "content": "2", "create_backup": False}, "c1")]),
            ChatResult(content="Wrote it."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified primes.txt exists."),
        ]
    )
    jarvis_env["manager"].provider = provider
    first = await AGENT.create_task(f"Write primes.txt at {target}", autonomy="autonomous", profile="fast")
    await AGENT._tasks[first.id]

    async with SessionLocal() as session:
        rows = (await session.execute(select(Trajectory))).scalars().all()
    assert len(rows) == 1
    assert rows[0].outcome == "completed"
    assert json.loads(rows[0].tools_json) == ["filesystem"]

    provider.turns = [ChatResult(content="Nothing to do."), ChatResult(content="Nothing to do.")]
    second = await AGENT.create_task(f"Write primes.txt at {target} again", autonomy="autonomous", profile="fast")
    await AGENT._tasks[second.id]

    system_prompts = [call[0].content for call in provider.calls if call and call[0].role == "system"]
    assert any("Lessons from similar earlier tasks" in text for text in system_prompts)
