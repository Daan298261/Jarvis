from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from app.agent.loop import AGENT
from app.agent.prompts import VERIFY_PROMPT, VERIFY_REQUIRED_PROMPT
from app.db.models import Task, TaskEvent
from app.db.session import SessionLocal
from app.providers.base import ChatResult


def _tool(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class ScriptedProvider:
    name = "scripted"

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
    runner = AGENT._tasks[task_id]
    await runner
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return task


async def test_task_cannot_complete_without_verification(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "verified.txt"
    provider = ScriptedProvider(
        [
            ChatResult(
                content=(
                    "END STATE: verified.txt exists\n"
                    "ACCEPTANCE CRITERIA:\n- file contains VERIFIED\n"
                    "PLAN:\n1. write the file\n2. read it back"
                )
            ),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "VERIFIED", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="The file is written. Task complete."),
            ChatResult(
                tool_calls=[
                    _tool("filesystem", {"action": "read", "path": str(target)}, "c2")
                ]
            ),
            ChatResult(content="Verified: verified.txt exists and contains VERIFIED."),
        ]
    )
    jarvis_env["manager"].provider = provider

    created = await AGENT.create_task(
        f"Write {target} containing VERIFIED and make sure it is actually there.",
        autonomy="autonomous",
        profile="fast",
        execution_mode="balanced",
    )
    task = await _finished(created.id)

    assert task.status == "completed"
    assert "VERIFIED" in (task.verification or "")
    assert task.acceptance_criteria
    assert "file contains VERIFIED" in task.acceptance_criteria
    assert target.exists()
    assert target.read_text(encoding="utf-8") == "VERIFIED"

    async with SessionLocal() as session:
        events = (await session.execute(select(TaskEvent).where(TaskEvent.task_id == task.id))).scalars().all()
    titles = [event.title for event in events]
    assert any("verification" in title.lower() for title in titles)
    assert any(
        any(getattr(message, "content", None) == VERIFY_PROMPT for message in call["messages"])
        for call in provider.calls
    )


async def test_reliable_mode_requires_verification_tool(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "reliable.txt"
    provider = ScriptedProvider(
        [
            ChatResult(content="END STATE: reliable.txt exists\nACCEPTANCE CRITERIA:\n- file exists\nPLAN:\n1. write file"),
            ChatResult(content="Plan looks fine."),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "OK", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="Done without checking."),
            ChatResult(content="It is definitely done."),
            ChatResult(
                tool_calls=[_tool("filesystem", {"action": "stat", "path": str(target)}, "c2")]
            ),
            ChatResult(content="Verified the file exists."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Create {target} with OK inside.",
        autonomy="autonomous",
        profile="fast",
        execution_mode="reliable",
    )
    task = await _finished(created.id)
    assert task.status == "completed"
    assert task.execution_mode == "reliable"
    assert "Verified" in (task.verification or "")
    required_seen = any(
        any(getattr(m, "content", None) == VERIFY_REQUIRED_PROMPT for m in call["messages"])
        for call in provider.calls
    )
    assert required_seen, "Reliable mode must demand a verification tool call"


async def test_task_survives_restart_checkpoint(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "persist.txt"
    provider = ScriptedProvider(
        [
            ChatResult(content="END STATE: persist.txt exists\nACCEPTANCE CRITERIA:\n- file exists\nPLAN:\n1. write"),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "KEEP", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="Wrote it."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified persist.txt contains KEEP."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(f"Write {target} with KEEP", autonomy="autonomous", profile="fast")
    task = await _finished(created.id)
    assert task.status == "completed"
    conversation = task.conversation_json
    assert conversation and conversation != "[]"

    async with SessionLocal() as session:
        reloaded = await session.get(Task, created.id)
        assert reloaded is not None
        assert reloaded.conversation_json == conversation
        assert reloaded.verification
