from __future__ import annotations

import json
from typing import Any

from app.agent.loop import AGENT
from app.db.models import Task
from app.db.session import SessionLocal
from app.providers.base import ChatResult


def _tool(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class ScriptedProvider:
    def __init__(self, turns: list[ChatResult]) -> None:
        self.turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    async def health(self) -> bool:
        return True

    async def chat(self, messages, tools=None, **kwargs) -> ChatResult:
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        if not self.turns:
            return ChatResult(content="Final report after script ended.")
        return self.turns.pop(0)


async def _finished(task_id: str) -> Task:
    await AGENT._tasks[task_id]
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return task


async def test_balanced_profile_thinks_on_plan_not_on_routine_tools(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "policy.txt"
    provider = ScriptedProvider(
        [
            ChatResult(
                content=(
                    "END STATE: policy.txt exists\n"
                    "ACCEPTANCE CRITERIA:\n- file contains POLICY\n"
                    "PLAN:\n1. write the file\n2. read it back"
                )
            ),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "POLICY", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="Wrote the file."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified policy.txt contains POLICY."),
        ]
    )
    jarvis_env["manager"].provider = provider

    created = await AGENT.create_task(
        f"Organize these files: write {target} containing POLICY on the desktop folder.",
        autonomy="autonomous",
        profile="balanced",
        execution_mode="balanced",
    )
    task = await _finished(created.id)
    assert task.status == "completed"
    assert task.task_class == "filesystem"

    thinking_flags = [call["kwargs"].get("thinking") for call in provider.calls]
    assert thinking_flags[0] is True
    later = thinking_flags[1:]
    assert False in later
    memory = json.loads(task.compact_memory or "{}")
    assert memory.get("recommended_context") == 8192
    assert memory.get("vision_requested") is False
