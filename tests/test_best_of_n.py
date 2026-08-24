from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from app.agent.loop import AGENT
from app.agent.planning import best_of_n_plan_prompt
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
    await AGENT._tasks[task_id]
    async with SessionLocal() as session:
        task = await session.get(Task, task_id)
        assert task is not None
        return task


def _user_texts(provider: ScriptedProvider) -> list[str]:
    texts: list[str] = []
    for call in provider.calls:
        for message in call["messages"]:
            if message.role == "user" and isinstance(message.content, str):
                texts.append(message.content)
    return texts


async def test_reliable_mode_selects_one_of_n_plans(jarvis_env):
    tmp = jarvis_env["tmp"]
    target = tmp / "chosen.txt"
    provider = ScriptedProvider(
        [
            ChatResult(
                content=(
                    "PLAN A\n"
                    "END STATE: chosen.txt exists via inspect-first\n"
                    "ACCEPTANCE CRITERIA:\n- file contains PICKED\n"
                    "PLAN:\n1. inspect the folder\n2. write chosen.txt\n"
                    "PLAN B\n"
                    "END STATE: chosen.txt exists via clicking\n"
                    "ACCEPTANCE CRITERIA:\n- file contains PICKED\n"
                    "PLAN:\n1. screenshot the desktop\n2. click Save\n"
                    "PLAN C\n"
                    "END STATE: chosen.txt exists via a shell loop\n"
                    "ACCEPTANCE CRITERIA:\n- file contains PICKED\n"
                    "PLAN:\n1. run a long shell script\n2. hope it worked\n"
                )
            ),
            ChatResult(content="SELECTED: A\nREASON: inspect then write is the most deterministic."),
            ChatResult(
                tool_calls=[
                    _tool(
                        "filesystem",
                        {"action": "write", "path": str(target), "content": "PICKED", "create_backup": False},
                        "c1",
                    )
                ]
            ),
            ChatResult(content="Wrote the file."),
            ChatResult(tool_calls=[_tool("filesystem", {"action": "read", "path": str(target)}, "c2")]),
            ChatResult(content="Verified chosen.txt contains PICKED."),
        ]
    )
    jarvis_env["manager"].provider = provider
    created = await AGENT.create_task(
        f"Create {target} containing PICKED.",
        autonomy="autonomous",
        profile="fast",
        execution_mode="reliable",
    )
    task = await _finished(created.id)
    assert task.status == "completed"
    assert target.read_text(encoding="utf-8") == "PICKED"
    assert "inspect" in (task.plan_json or "")

    texts = _user_texts(provider)
    assert any("PLAN A" in text and "PLAN B" in text for text in texts)
    assert any(text.startswith("Critique these candidate plans") for text in texts)
    assert any("The selected plan is PLAN A" in text for text in texts)

    async with SessionLocal() as session:
        events = (await session.execute(select(TaskEvent).where(TaskEvent.task_id == task.id))).scalars().all()
    titles = [event.title for event in events]
    assert any("Comparing candidate plans" in title for title in titles)
    assert any("Selected plan A" in title for title in titles)


def test_best_of_n_prompt_asks_for_labeled_plans():
    prompt = best_of_n_plan_prompt(3)
    assert "PLAN A" in prompt
    assert "PLAN B" in prompt
    assert "Do not call tools yet" in prompt
